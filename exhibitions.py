import asyncio
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Optional, Set
from datetime import datetime
from browser_use import Agent, ChatOpenAI, Tools, Browser
from browser_use.agent.views import ActionResult
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

load_dotenv()

class ExhibitionData(BaseModel):
    """Pydantic model for structured exhibition data input"""
    title: str = Field(..., description="The exhibition title")
    main_artist: Optional[str] = Field(None, description="Primary artist name only (clean name without birth/death dates or extra descriptive text)")
    other_artists: Optional[List[str]] = Field(default_factory=list, description="Other featured artists (clean names only, no dates or extra info)")
    start_date: Optional[str] = Field(None, description="Exhibition start date")
    end_date: Optional[str] = Field(None, description="Exhibition end date")
    museum: Optional[str] = Field(None, description="Museum name")
    details: Optional[str] = Field(None, description="Brief exhibition description")
    url: Optional[str] = Field(None, description="Direct URL to exhibition page")

@dataclass
class Exhibition:
    title: str
    main_artist: Optional[str] = None
    other_artists: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum: Optional[str] = None
    details: Optional[str] = None
    url: Optional[str] = None

class ExhibitionScraper:
    def __init__(self, llm_model="gpt-4o-mini"):
        self.llm = ChatOpenAI(model=llm_model)
        self.exhibitions: List[Exhibition] = []
        self.seen_exhibitions: Set[str] = set()  # Track exhibition titles to avoid duplicates
        self.tools = Tools()
        self._setup_custom_tools()
    
    def _setup_custom_tools(self):
        """Setup custom tools for exhibition data collection"""
        
        @self.tools.action(
            description="Save or update exhibition data to the results list using structured format",
            param_model=ExhibitionData
        )
        def save_exhibition_data(params: ExhibitionData) -> ActionResult:
            """Save exhibition information to the results with duplicate checking"""
            
            # Create a unique key for the exhibition (title + museum)
            exhibition_key = f"{params.title.lower().strip()}_{params.museum or ''}".lower()
            
            # Check if we already have this exhibition
            existing_exhibition = None
            for i, exhibition in enumerate(self.exhibitions):
                existing_key = f"{exhibition.title.lower().strip()}_{exhibition.museum or ''}".lower()
                if existing_key == exhibition_key:
                    existing_exhibition = i
                    break
            
            if existing_exhibition is not None:
                # Update existing exhibition with more complete data
                current = self.exhibitions[existing_exhibition]
                
                # Update fields if new data is more complete
                updated_exhibition = Exhibition(
                    title=params.title,
                    main_artist=params.main_artist or current.main_artist,
                    other_artists=params.other_artists if params.other_artists else current.other_artists,
                    start_date=params.start_date or current.start_date,
                    end_date=params.end_date or current.end_date,
                    museum=params.museum or current.museum,
                    details=params.details if params.details and len(params.details) > len(current.details or "") else current.details,
                    url=params.url or current.url
                )
                
                self.exhibitions[existing_exhibition] = updated_exhibition
                return ActionResult(
                    extracted_content=f"Updated existing exhibition: {params.title}",
                    long_term_memory=f"Exhibition '{params.title}' updated with additional details"
                )
            else:
                # Add new exhibition
                exhibition = Exhibition(
                    title=params.title,
                    main_artist=params.main_artist,
                    other_artists=params.other_artists,
                    start_date=params.start_date,
                    end_date=params.end_date,
                    museum=params.museum,
                    details=params.details,
                    url=params.url
                )
                self.exhibitions.append(exhibition)
                self.seen_exhibitions.add(exhibition_key)
                
                return ActionResult(
                    extracted_content=f"Saved new exhibition: {params.title}",
                    long_term_memory=f"Exhibition '{params.title}' saved to results"
                )

    async def scrape_museum_exhibitions(self, museum_urls: List[str]) -> List[Exhibition]:
        """
        Scrape exhibitions from a list of museum URLs
        
        Args:
            museum_urls: List of museum exhibition page URLs
            
        Returns:
            List of Exhibition objects containing scraped data
        """
        
        for url in museum_urls:
            print(f"Scraping exhibitions from: {url}")
            
            try:
                agent = Agent(
                    task=f"""
                    Visit {url} and find all current and upcoming exhibitions.
                    
                    IMPORTANT INSTRUCTIONS:
                    1. First, scan the main exhibitions page and collect basic information for ALL exhibitions
                    2. Then, click into individual exhibition pages to get more detailed information
                    3. Use the save_exhibition_data tool for each exhibition - it will automatically handle duplicates and updates
                    
                    For each exhibition, extract:
                    - title: The exhibition title (required)
                    - main_artist: The PRIMARY or FEATURED artist (just the name, no birth/death dates)
                    - other_artists: List of other significant artists featured (names only, no dates)
                    - start_date: Exhibition start date if available
                    - end_date: Exhibition end date if available  
                    - museum: Museum name (try to find it on the page)
                    - details: Brief description/summary (optional - only if easily visible)
                    - url: Direct URL link to the exhibition page
                    
                    ARTIST NAME GUIDELINES:
                    - For main_artist: Use only the PRIMARY featured artist
                    - Remove birth/death dates like "(1757-1827)" 
                    - Remove extra descriptive text
                    - Example: "William Blake (1757-1827)" becomes just "William Blake"
                    - If multiple equally important artists, pick the first mentioned as main_artist
                    
                    Look for:
                    - Current exhibitions  
                    - Upcoming exhibitions
                    - Featured exhibitions
                    - Any exhibition listings or galleries
                    
                    The tool will automatically prevent duplicates and merge information when you visit individual exhibition pages.
                    """,
                    llm=self.llm,
                    tools=self.tools,
					browser=Browser(
						headless=True,
						enable_default_extensions=False,
					),
					use_vision=False,
                )
                
                await agent.run(max_steps=20)
                
            except Exception as e:
                print(f"Error scraping {url}: {str(e)}")
                continue
        
        return self.exhibitions
    
    def save_to_json(self, filename: str = "exhibitions_v2.json"):
        """Save exhibitions to JSON file"""
        exhibitions_dict = [asdict(exhibition) for exhibition in self.exhibitions]
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(exhibitions_dict, f, indent=2, ensure_ascii=False)
        
        print(f"Saved {len(self.exhibitions)} exhibitions to {filename}")
    
    def print_results(self):
        """Print all found exhibitions"""
        print(f"\nFound {len(self.exhibitions)} exhibitions:")
        print("=" * 80)
        
        for i, exhibition in enumerate(self.exhibitions, 1):
            print(f"{i}. {exhibition.title}")
            if exhibition.main_artist:
                print(f"   Main Artist: {exhibition.main_artist}")
            if exhibition.other_artists:
                other_artists_str = ", ".join(exhibition.other_artists)
                print(f"   Other Artists: {other_artists_str}")
            if exhibition.start_date or exhibition.end_date:
                date_range = f"{exhibition.start_date or 'TBD'} - {exhibition.end_date or 'TBD'}"
                print(f"   Dates: {date_range}")
            if exhibition.museum:
                print(f"   Museum: {exhibition.museum}")
            if exhibition.url:
                print(f"   URL: {exhibition.url}")
            if exhibition.details:
                print(f"   Details: {exhibition.details[:100]}{'...' if len(exhibition.details) > 100 else ''}")
            print()

async def main():
    """Main function to run the exhibition scraper"""
    
    # List of museum exhibition URLs to scrape
    museum_urls = [
        "https://www.nationalgallery.ie/art-and-artists/exhibitions",
        # Add more museum URLs here
    ]
    
    # Create scraper instance
    scraper = ExhibitionScraper()
    
    # Scrape exhibitions
    exhibitions = await scraper.scrape_museum_exhibitions(museum_urls)
    
    # Print results
    scraper.print_results()
    
    # Save to JSON file
    scraper.save_to_json()

if __name__ == "__main__":
    asyncio.run(main())