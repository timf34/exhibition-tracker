import asyncio
import json
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime
from browser_use import Agent, ChatOpenAI, Tools
from browser_use.agent.views import ActionResult
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Exhibition:
    title: str
    artists: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum: Optional[str] = None
    details: Optional[str] = None
    url: Optional[str] = None

class ExhibitionScraper:
    def __init__(self, llm_model="gpt-5-mini"):
        self.llm = ChatOpenAI(model=llm_model)
        self.exhibitions: List[Exhibition] = []
        self.tools = Tools()
        self._setup_custom_tools()
    
    def _setup_custom_tools(self):
        """Setup custom tools for exhibition data collection"""
        
        @self.tools.action(description="Save exhibition data to the results list")
        def save_exhibition_data(
            title: str,
            artists: str = None,
            start_date: str = None,
            end_date: str = None,
            museum: str = None,
            details: str = None,
            url: str = None
        ) -> ActionResult:
            """Save exhibition information to the results"""
            # Convert artist string to list if provided
            artists_list = None
            if artists:
                # Split by common separators and clean up
                artists_list = [artist.strip() for artist in artists.replace(' and ', ', ').split(',') if artist.strip()]
            
            exhibition = Exhibition(
                title=title,
                artists=artists_list,
                start_date=start_date,
                end_date=end_date,
                museum=museum,
                details=details,
                url=url
            )
            self.exhibitions.append(exhibition)
            return ActionResult(
                extracted_content=f"Saved exhibition: {title}",
                long_term_memory=f"Exhibition '{title}' saved to results"
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
                    
                    For each exhibition, extract:
                    - Title (required)
                    - Artist name(s) if available (pass as comma-separated string for multiple artists)
                    - Start date if available
                    - End date if available  
                    - Museum name (try to find it on the page)
                    - Brief details/summary (optional - only if easily visible)
                    - Direct URL link to the exhibition if available
                    
                    Use the save_exhibition_data tool for each exhibition you find.
                    When passing artists, use the 'artists' parameter with a comma-separated string of artist names.
                    
                    Look for:
                    - Current exhibitions
                    - Upcoming exhibitions
                    - Featured exhibitions
                    - Any exhibition listings or galleries
                    
                    Click through exhibition links if needed to get more complete information.
                    """,
                    llm=self.llm,
                    tools=self.tools,
					headless=True,
                )
                
                await agent.run(max_steps=15)
                
            except Exception as e:
                print(f"Error scraping {url}: {str(e)}")
                continue
        
        return self.exhibitions
    
    def save_to_json(self, filename: str = "exhibitions.json"):
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
            if exhibition.artists:
                artists_str = ", ".join(exhibition.artists)
                print(f"   Artists: {artists_str}")
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
        # "https://www.guggenheim.org/exhibitions",
        # "https://www.metmuseum.org/exhibitions",
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