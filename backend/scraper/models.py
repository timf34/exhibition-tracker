"""
Data models and database schema for exhibition aggregator
"""
import sqlite3
from datetime import datetime, UTC
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from pathlib import Path
import json

# -------------------- Data Models --------------------

@dataclass
class Museum:
    city: str
    country: str
    name: str
    url: str
    last_scraped: Optional[datetime] = None
    scrape_status: str = "pending"  # pending, success, failed
    exhibition_count: int = 0

@dataclass
class Exhibition:
    title: str
    main_artist: Optional[str] = None
    other_artists: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum_name: str = None
    museum_city: str = None
    museum_country: str = None
    details: Optional[str] = None
    url: Optional[str] = None
    scraped_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        if self.other_artists:
            d['other_artists'] = json.dumps(self.other_artists) if isinstance(self.other_artists, list) else self.other_artists
        if self.scraped_at:
            d['scraped_at'] = self.scraped_at.isoformat()
        return d

class ExhibitionListItem(BaseModel):
    title: str
    href: str
    date_text: Optional[str] = None

class ExhibitionRecord(BaseModel):
    title: str
    main_artist: Optional[str] = None
    other_artists: Optional[List[str]] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum: Optional[str] = None
    details: Optional[str] = None
    url: Optional[str] = None

# -------------------- Database Manager --------------------

class DatabaseManager:
    def __init__(self, db_path: str = "backend/data/exhibitions.db"):
        self.db_path = Path(db_path)
        self.json_path = self.db_path.parent / "exhibitions.json"  # JSON file alongside DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Create tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS museums (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city TEXT NOT NULL,
                    country TEXT NOT NULL,
                    name TEXT NOT NULL UNIQUE,
                    url TEXT NOT NULL,
                    last_scraped TIMESTAMP,
                    scrape_status TEXT DEFAULT 'pending',
                    exhibition_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exhibitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    main_artist TEXT,
                    other_artists TEXT,  -- JSON array
                    start_date TEXT,
                    end_date TEXT,
                    museum_name TEXT NOT NULL,
                    museum_city TEXT,
                    museum_country TEXT,
                    details TEXT,
                    url TEXT,
                    scraped_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(title, museum_name, start_date)
                )
            """)
            
            # Create indexes for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exhibitions_dates ON exhibitions(start_date, end_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exhibitions_city ON exhibitions(museum_city)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exhibitions_country ON exhibitions(museum_country)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_museums_last_scraped ON museums(last_scraped)")
    
    def get_museums_to_scrape(self, days_old: int = 90) -> List[Museum]:
        """Get museums that haven't been scraped in X days"""
        cutoff_date = datetime.now(UTC).timestamp() - (days_old * 24 * 60 * 60)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM museums 
                WHERE last_scraped IS NULL 
                   OR last_scraped < datetime(?, 'unixepoch')
                ORDER BY last_scraped ASC
            """, (cutoff_date,))
            
            museums = []
            for row in cursor:
                museums.append(Museum(
                    city=row['city'],
                    country=row['country'],
                    name=row['name'],
                    url=row['url'],
                    last_scraped=datetime.fromisoformat(row['last_scraped']) if row['last_scraped'] else None,
                    scrape_status=row['scrape_status'],
                    exhibition_count=row['exhibition_count']
                ))
            return museums
    
    def update_museum_status(self, museum_name: str, status: str, 
                           exhibition_count: int = 0, error: str = None):
        """Update museum scraping status"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE museums 
                SET last_scraped = CURRENT_TIMESTAMP,
                    scrape_status = ?,
                    exhibition_count = ?,
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
            """, (status, exhibition_count, error, museum_name))
    
    def save_exhibitions(self, exhibitions: List[Exhibition], museum_name: str):
        """Save exhibitions, replacing old ones for this museum"""
        with sqlite3.connect(self.db_path) as conn:
            # Delete old exhibitions for this museum
            conn.execute("DELETE FROM exhibitions WHERE museum_name = ?", (museum_name,))

            # Insert new exhibitions
            for ex in exhibitions:
                # Accept either dataclass Exhibition or plain dict (defensive)
                if hasattr(ex, "to_dict"):
                    ex_dict = ex.to_dict()
                elif isinstance(ex, dict):
                    ex_dict = dict(ex)
                else:
                    # fallback: try to asdict
                    try:
                        from dataclasses import asdict
                        ex_dict = asdict(ex)
                    except Exception:
                        ex_dict = {}

                # Ensure other_artists is a JSON string or None
                oa = ex_dict.get("other_artists")
                if isinstance(oa, list):
                    try:
                        oa_val = json.dumps(oa, ensure_ascii=False)
                    except Exception:
                        # last-resort: convert elements to str then dump
                        oa_val = json.dumps([str(x) for x in oa], ensure_ascii=False)
                elif oa is None:
                    oa_val = None
                else:
                    # if it's already a string (hopefully JSON), keep it
                    oa_val = oa

                # Ensure scraped_at is an ISO string (SQLite expects text)
                scraped_at = ex_dict.get("scraped_at")
                if scraped_at is None:
                    scraped_at_val = datetime.now(UTC).isoformat()
                elif isinstance(scraped_at, str):
                    scraped_at_val = scraped_at
                else:
                    # if it's a datetime, convert; otherwise stringify
                    try:
                        scraped_at_val = scraped_at.isoformat()
                    except Exception:
                        scraped_at_val = str(scraped_at)

                # Build params in same order as the INSERT statement
                params = (
                    ex_dict.get('title'),
                    ex_dict.get('main_artist'),
                    oa_val,
                    ex_dict.get('start_date'),
                    ex_dict.get('end_date'),
                    ex_dict.get('museum_name') or museum_name,
                    ex_dict.get('museum_city'),
                    ex_dict.get('museum_country'),
                    ex_dict.get('details'),
                    ex_dict.get('url'),
                    scraped_at_val
                )

                # Debugging: if any param is a list (shouldn't happen), show details
                for i, p in enumerate(params, start=1):
                    if isinstance(p, (list, dict, set)):
                        print(f"[DB DEBUG] Unexpected non-scalar param at index {i} for title={ex_dict.get('title')}: {type(p)} -> {p}")

                conn.execute("""
                    INSERT OR IGNORE INTO exhibitions (
                        title, main_artist, other_artists, start_date, end_date,
                        museum_name, museum_city, museum_country, details, url, scraped_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, params)

        # Also save all exhibitions to JSON file for easy viewing
        self._export_to_json()
        print(f"[DB] Saved {len(exhibitions)} exhibitions for {museum_name} to DB and JSON")
    
    def _export_to_json(self):
        """Export all current exhibitions to JSON file"""
        try:
            all_exhibitions = self.get_all_exhibitions_for_export()
            
            # Save to JSON with pretty formatting
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(all_exhibitions, f, indent=2, ensure_ascii=False, default=str)
            
            print(f"[DB] Exported {len(all_exhibitions)} exhibitions to {self.json_path}")
        except Exception as e:
            print(f"[DB] Error exporting to JSON: {e}")
    
    def get_all_exhibitions_for_export(self) -> List[Dict]:
        """Get all exhibitions formatted for export"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM exhibitions 
                ORDER BY museum_country, museum_city, museum_name, start_date
            """)
            
            exhibitions = []
            for row in cursor:
                ex_dict = dict(row)
                # Parse other_artists JSON if present
                if ex_dict.get('other_artists'):
                    try:
                        ex_dict['other_artists'] = json.loads(ex_dict['other_artists'])
                    except:
                        pass
                exhibitions.append(ex_dict)
            
            return exhibitions
    
    def search_exhibitions(self, city: str = None, country: str = None, 
                         artist: str = None, current_only: bool = True) -> List[Dict]:
        """Search exhibitions with filters"""
        query = "SELECT * FROM exhibitions WHERE 1=1"
        params = []
        
        if city:
            query += " AND LOWER(museum_city) = LOWER(?)"
            params.append(city)
        
        if country:
            query += " AND LOWER(museum_country) = LOWER(?)"
            params.append(country)
        
        if artist:
            query += " AND (LOWER(main_artist) LIKE LOWER(?) OR LOWER(other_artists) LIKE LOWER(?))"
            params.extend([f'%{artist}%', f'%{artist}%'])
        
        if current_only:
            # Only show exhibitions that haven't ended
            query += " AND (end_date IS NULL OR date(end_date) >= date('now'))"
        
        query += " ORDER BY start_date, museum_city, museum_name"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            
            results = []
            for row in cursor:
                ex_dict = dict(row)
                if ex_dict.get('other_artists'):
                    try:
                        ex_dict['other_artists'] = json.loads(ex_dict['other_artists'])
                    except:
                        pass
                results.append(ex_dict)
            
            return results
    
    def get_cities_with_exhibitions(self) -> List[Dict[str, Any]]:
        """Get list of cities with current exhibition counts"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    museum_city as city,
                    museum_country as country,
                    COUNT(*) as exhibition_count,
                    COUNT(DISTINCT museum_name) as museum_count
                FROM exhibitions 
                WHERE end_date IS NULL OR date(end_date) >= date('now')
                GROUP BY museum_city, museum_country
                ORDER BY exhibition_count DESC
            """)
            
            return [dict(row) for row in cursor]
    
    def import_museums_from_csv(self, csv_path: str):
        """Import museums from CSV file"""
        import csv
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            with sqlite3.connect(self.db_path) as conn:
                count = 0
                for row in reader:
                    # Upsert museum
                    conn.execute("""
                        INSERT OR REPLACE INTO museums (city, country, name, url)
                        VALUES (?, ?, ?, ?)
                    """, (
                        row['city'].strip(),
                        row['country'].strip(),
                        row['museum'].strip(),
                        row['url'].strip()
                    ))
                    count += 1
                    
        print(f"[DB] Imported {count} museums from {csv_path}")