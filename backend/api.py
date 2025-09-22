"""
FastAPI backend for serving exhibition data
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio

from models import DatabaseManager
from scheduler import MuseumScheduler

app = FastAPI(title="Art Exhibition Aggregator API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
db = DatabaseManager()
scheduler = MuseumScheduler()

# -------------------- API Endpoints --------------------

@app.get("/")
def read_root():
    """API health check"""
    return {"status": "healthy", "service": "Art Exhibition Aggregator"}

@app.get("/api/exhibitions")
def get_exhibitions(
    city: Optional[str] = Query(None, description="Filter by city"),
    country: Optional[str] = Query(None, description="Filter by country"),
    artist: Optional[str] = Query(None, description="Search by artist name"),
    current_only: bool = Query(True, description="Show only current/future exhibitions")
) -> List[Dict]:
    """
    Get exhibitions with optional filters
    
    Examples:
    - /api/exhibitions?city=Paris
    - /api/exhibitions?country=France
    - /api/exhibitions?artist=Picasso
    """
    try:
        exhibitions = db.search_exhibitions(
            city=city,
            country=country,
            artist=artist,
            current_only=current_only
        )
        
        # Add computed fields
        for ex in exhibitions:
            # Parse dates for frontend
            if ex.get('start_date'):
                ex['start_date_parsed'] = ex['start_date']
            if ex.get('end_date'):
                ex['end_date_parsed'] = ex['end_date']
            
            # Status indicator
            if ex.get('end_date'):
                try:
                    end = datetime.strptime(ex['end_date'], "%d %B %Y")
                    ex['is_ending_soon'] = (end - datetime.now()).days <= 14
                except:
                    ex['is_ending_soon'] = False
        
        return exhibitions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cities")
def get_cities() -> List[Dict[str, Any]]:
    """
    Get all cities with exhibition counts
    
    Returns cities sorted by number of current exhibitions
    """
    try:
        cities = db.get_cities_with_exhibitions()
        return cities
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/museums")
def get_museums() -> List[Dict]:
    """Get all museums with their scraping status"""
    try:
        museums = db.get_museums_to_scrape(days_old=99999)  # Get all
        return [
            {
                "name": m.name,
                "city": m.city,
                "country": m.country,
                "url": m.url,
                "last_scraped": m.last_scraped.isoformat() if m.last_scraped else None,
                "status": m.scrape_status,
                "exhibition_count": m.exhibition_count
            }
            for m in museums
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/scrape/museum/{museum_name}")
async def scrape_museum(museum_name: str, background_tasks: BackgroundTasks):
    """
    Trigger scraping for a specific museum
    
    Runs in background and returns immediately
    """
    try:
        # Add to background tasks
        background_tasks.add_task(
            scheduler.scrape_specific_museum,
            museum_name
        )
        
        return {
            "status": "started",
            "message": f"Scraping started for {museum_name}",
            "museum": museum_name
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/scrape/outdated")
async def scrape_outdated(background_tasks: BackgroundTasks):
    """
    Trigger scraping for all outdated museums
    
    Runs in background and returns immediately
    """
    try:
        # Add to background tasks
        background_tasks.add_task(
            scheduler.scrape_outdated_museums
        )
        
        return {
            "status": "started",
            "message": "Scraping started for outdated museums"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
def get_stats() -> Dict[str, Any]:
    """Get aggregated statistics"""
    try:
        # Get total counts
        all_exhibitions = db.search_exhibitions(current_only=True)
        all_museums = db.get_museums_to_scrape(days_old=99999)
        cities = db.get_cities_with_exhibitions()
        
        # Calculate stats
        stats = {
            "total_exhibitions": len(all_exhibitions),
            "total_museums": len(all_museums),
            "total_cities": len(cities),
            "total_countries": len(set(c["country"] for c in cities)),
            "last_updated": max(
                (m.last_scraped for m in all_museums if m.last_scraped),
                default=None
            ),
            "top_cities": cities[:5]  # Top 5 cities by exhibition count
        }
        
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/search")
def search(q: str = Query(..., description="Search query")) -> Dict[str, Any]:
    """
    Global search across exhibitions, artists, and museums
    """
    try:
        results = {
            "exhibitions": [],
            "artists": set(),
            "cities": set()
        }
        
        # Search exhibitions by title and artist
        all_exhibitions = db.search_exhibitions(current_only=True)
        
        for ex in all_exhibitions:
            q_lower = q.lower()
            
            # Check if query matches exhibition title
            if q_lower in (ex.get('title') or '').lower():
                results["exhibitions"].append(ex)
            
            # Check if query matches artist
            elif ex.get('main_artist') and q_lower in ex['main_artist'].lower():
                results["exhibitions"].append(ex)
                results["artists"].add(ex['main_artist'])
            
            # Check if query matches museum
            elif q_lower in (ex.get('museum_name') or '').lower():
                results["exhibitions"].append(ex)
            
            # Check city
            if ex.get('museum_city') and q_lower in ex['museum_city'].lower():
                results["cities"].add(ex['museum_city'])
        
        return {
            "query": q,
            "exhibitions": results["exhibitions"][:50],  # Limit results
            "artists": list(results["artists"]),
            "cities": list(results["cities"])
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------- Run the API --------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)