"""
Smart scheduler for museum scraping with incremental updates
"""
import asyncio
import csv
from datetime import datetime, UTC
from pathlib import Path
from typing import List, Dict, Any, Tuple
import logging

# Support running either from project root (python -m backend.scheduler)
# or from inside backend directory (python scheduler.py)
from backend.scraper.models import DatabaseManager, Museum, Exhibition
from backend.scraper.condenser import PageCondenser
from backend.scraper.extractor import LLMExtractor
from backend.scraper.orchestrator import ExhibitionsOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MuseumScheduler:
    def __init__(self, db_path: str = "backend/data/exhibitions.db", 
                 csv_path: str = "backend/data/museums.csv",
                 days_until_rescrape: int = 90):
        """
        Initialize scheduler
        
        Args:
            db_path: Path to SQLite database
            csv_path: Path to museums CSV file
            days_until_rescrape: Days before a museum needs re-scraping
        """
        self.db = DatabaseManager(db_path)
        self.csv_path = Path(csv_path)
        self.days_until_rescrape = days_until_rescrape
        
    def sync_museums_from_csv(self):
        """Sync museums from CSV to database"""
        if not self.csv_path.exists():
            logger.error(f"CSV file not found: {self.csv_path}")
            return
        
        logger.info(f"Syncing museums from {self.csv_path}")
        self.db.import_museums_from_csv(str(self.csv_path))
    
    async def scrape_museum(self, museum: Museum) -> Dict[str, Any]:
        """Scrape a single museum"""
        logger.info(f"Starting scrape for {museum.name} ({museum.city}, {museum.country})")
        
        # Initialize scraping components
        condenser = PageCondenser()
        llm = LLMExtractor(model_listing="gpt-5-mini", model_detail="gpt-5-mini")
        if ExhibitionsOrchestrator is None:
            raise RuntimeError(
                "ExhibitionsOrchestrator not found. Ensure 'backend/scraper/orchestrator.py' exists "
                "or install the scraper module."
            )
        orchestrator = ExhibitionsOrchestrator(
            condenser, llm, 
            follow_pagination=True, 
            detail_concurrency=12, 
            cache=True
        )
        
        try:
            # Run the scraper
            result = await orchestrator.run_for_museum(museum.name, museum.url)
            
            # Convert to Exhibition objects with location data
            exhibitions = []
            for ex_dict in result["exhibitions"]:
                ex = Exhibition(
                    title=ex_dict['title'],
                    main_artist=ex_dict.get('main_artist'),
                    other_artists=ex_dict.get('other_artists'),
                    start_date=ex_dict.get('start_date'),
                    end_date=ex_dict.get('end_date'),
                    museum_name=museum.name,
                    museum_city=museum.city,
                    museum_country=museum.country,
                    details=ex_dict.get('details'),
                    url=ex_dict.get('url'),
                    scraped_at=datetime.now(UTC)
                )
                exhibitions.append(ex)
            
            # Save to database
            self.db.save_exhibitions(exhibitions, museum.name)
            self.db.update_museum_status(
                museum.name, 
                status="success",
                exhibition_count=len(exhibitions)
            )
            
            logger.info(f"✓ {museum.name}: Saved {len(exhibitions)} exhibitions")
            
            # Close the HTTP client
            await condenser.close()
            
            return {
                "status": "success",
                "museum": museum.name,
                "exhibitions_count": len(exhibitions),
                "summary": result["summary"]
            }
            
        except Exception as e:
            logger.error(f"✗ {museum.name}: Failed with error: {e}")
            self.db.update_museum_status(
                museum.name,
                status="failed",
                error=str(e)
            )
            
            # Ensure client is closed even on error
            try:
                await condenser.close()
            except:
                pass
                
            return {
                "status": "failed",
                "museum": museum.name,
                "error": str(e)
            }
    
    async def scrape_outdated_museums(self, max_concurrent: int = 3):
        """
        Scrape all museums that need updating
        
        Args:
            max_concurrent: Maximum number of concurrent museum scrapes
        """
        # First, sync museums from CSV
        self.sync_museums_from_csv()
        
        # Get museums that need scraping
        museums_to_scrape = self.db.get_museums_to_scrape(self.days_until_rescrape)
        
        if not museums_to_scrape:
            logger.info("All museums are up to date!")
            return {"status": "up_to_date", "museums_scraped": 0}
        
        logger.info(f"Found {len(museums_to_scrape)} museums to scrape")
        
        # Scrape museums with concurrency limit
        results = []
        for i in range(0, len(museums_to_scrape), max_concurrent):
            batch = museums_to_scrape[i:i + max_concurrent]
            logger.info(f"Processing batch {i//max_concurrent + 1} ({len(batch)} museums)")
            
            # Run batch concurrently
            batch_results = await asyncio.gather(
                *[self.scrape_museum(museum) for museum in batch],
                return_exceptions=True
            )
            
            results.extend(batch_results)
            
            # Small delay between batches to avoid rate limiting
            if i + max_concurrent < len(museums_to_scrape):
                await asyncio.sleep(2)
        
        # Summarize results
        successful = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "success")
        failed = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "failed")
        
        logger.info(f"Scraping complete: {successful} successful, {failed} failed")
        
        return {
            "status": "complete",
            "museums_scraped": successful,
            "museums_failed": failed,
            "results": results
        }
    
    async def scrape_specific_museum(self, museum_name: str):
        """Scrape a specific museum by name"""
        # Get museum details from database
        museums = self.db.get_museums_to_scrape(days_old=99999)  # Get all museums
        museum = next((m for m in museums if m.name == museum_name), None)
        
        if not museum:
            logger.error(f"Museum '{museum_name}' not found in database")
            return {"status": "error", "message": f"Museum not found: {museum_name}"}
        
        return await self.scrape_museum(museum)

# -------------------- CLI Interface --------------------

async def main():
    """Command line interface for the scheduler"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Museum Exhibition Scraper")
    parser.add_argument(
        "--action",
        choices=["update", "scrape-all", "scrape-museum", "sync-csv"],
        default="update",
        help="Action to perform"
    )
    parser.add_argument(
        "--museum",
        help="Museum name for scrape-museum action"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Days before museum needs re-scraping (default: 90)"
    )
    parser.add_argument(
        "--csv",
        default="backend/data/museums.csv",
        help="Path to museums CSV file"
    )
    parser.add_argument(
        "--db",
        default="backend/data/exhibitions.db",
        help="Path to database file"
    )
    
    args = parser.parse_args()
    
    # Initialize scheduler
    scheduler = MuseumScheduler(
        db_path=args.db,
        csv_path=args.csv,
        days_until_rescrape=args.days
    )
    
    if args.action == "sync-csv":
        scheduler.sync_museums_from_csv()
        print("Museums synced from CSV")
        
    elif args.action == "update":
        result = await scheduler.scrape_outdated_museums()
        print(f"Update complete: {result['museums_scraped']} museums updated")
        
    elif args.action == "scrape-all":
        # Force scrape all by setting days to 0
        scheduler.days_until_rescrape = 0
        result = await scheduler.scrape_outdated_museums()
        print(f"Full scrape complete: {result['museums_scraped']} museums scraped")
        
    elif args.action == "scrape-museum":
        if not args.museum:
            print("ERROR: --museum name required for scrape-museum action")
            return
        result = await scheduler.scrape_specific_museum(args.museum)
        if result["status"] == "success":
            print(f"✓ {args.museum}: {result['exhibitions_count']} exhibitions found")
        else:
            print(f"✗ {args.museum}: {result.get('error', 'Unknown error')}")

if __name__ == "__main__":
    asyncio.run(main())