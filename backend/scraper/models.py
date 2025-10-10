"""
Improved data models and database schema for exhibition aggregator
"""
import sqlite3
import re
from datetime import datetime, UTC
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from pathlib import Path
import json
import unicodedata

# -------------------- Data Models --------------------

@dataclass
class Museum:
    id: Optional[int]
    name: str
    city_name: str
    country_name: str
    url: str
    last_scraped: Optional[datetime] = None
    scrape_status: str = "pending"
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
    details: Optional[str] = None
    url: Optional[str] = None

# -------------------- Database Manager --------------------

class DatabaseManager:
    def __init__(self, db_path: str = "backend/data/exhibitions.db"):
        self.db_path = Path(db_path)
        self.json_path = self.db_path.parent / "exhibitions.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def normalize_artist_name(self, name: str) -> str:
        """Normalize artist names for deduplication"""
        if not name:
            return ""
        # Remove accents, convert to lowercase, remove extra spaces and punctuation
        name = unicodedata.normalize('NFKD', name)
        name = ''.join(c for c in name if not unicodedata.combining(c))
        name = re.sub(r'[^\w\s]', ' ', name.lower())
        return ' '.join(name.split())
    
    def parse_date_to_iso(self, date_text: str) -> Optional[str]:
        if not date_text:
            return None
        return self._parse_single_date(date_text)
    
    def init_database(self):
        """Create normalized database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            
            # Countries table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS countries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    code TEXT UNIQUE
                )
            """)
            
            # Cities table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    country_id INTEGER NOT NULL,
                    latitude REAL,
                    longitude REAL,
                    FOREIGN KEY (country_id) REFERENCES countries(id),
                    UNIQUE(name, country_id)
                )
            """)
            
            # Museums table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS museums (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    city_id INTEGER NOT NULL,
                    url TEXT,
                    last_scraped TIMESTAMP,
                    scrape_status TEXT DEFAULT 'pending',
                    exhibition_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (city_id) REFERENCES cities(id),
                    UNIQUE(name, city_id)
                )
            """)
            
            # Artists table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    birth_year INTEGER,
                    death_year INTEGER,
                    nationality TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Exhibitions table with proper dates
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exhibitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    museum_id INTEGER NOT NULL,
                    start_date_iso DATE,
                    end_date_iso DATE,
                    start_date_text TEXT,
                    end_date_text TEXT,
                    details TEXT,
                    url TEXT,
                    scraped_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (museum_id) REFERENCES museums(id),
                    UNIQUE(title, museum_id, start_date_iso)
                )
            """)
            
            # Many-to-many for exhibition artists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exhibition_artists (
                    exhibition_id INTEGER NOT NULL,
                    artist_id INTEGER NOT NULL,
                    role TEXT DEFAULT 'featured',
                    PRIMARY KEY (exhibition_id, artist_id),
                    FOREIGN KEY (exhibition_id) REFERENCES exhibitions(id) ON DELETE CASCADE,
                    FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE
                )
            """)
            
            # Create performance indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_exhibitions_dates ON exhibitions(start_date_iso, end_date_iso)",
                "CREATE INDEX IF NOT EXISTS idx_exhibitions_museum ON exhibitions(museum_id)",
                "CREATE INDEX IF NOT EXISTS idx_museums_city ON museums(city_id)",
                "CREATE INDEX IF NOT EXISTS idx_artists_normalized ON artists(normalized_name)",
                "CREATE INDEX IF NOT EXISTS idx_exhibition_artists_exhibition ON exhibition_artists(exhibition_id)",
                "CREATE INDEX IF NOT EXISTS idx_exhibition_artists_artist ON exhibition_artists(artist_id)",
                "CREATE INDEX IF NOT EXISTS idx_cities_country ON cities(country_id)"
            ]
            
            for index_sql in indexes:
                conn.execute(index_sql)
            
            # Create FTS5 virtual table if available
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS exhibitions_fts USING fts5(
                        title, details, artist_names,
                        content='',
                        tokenize='porter unicode61'
                    )
                """)
                print("[DB] FTS5 search enabled")
            except sqlite3.OperationalError as e:
                print(f"[DB] FTS5 not available: {e}")
    
    def get_or_create_country(self, conn, country_name: str, code: str = None) -> int:
        """Get country ID, creating if necessary"""
        cursor = conn.execute("SELECT id FROM countries WHERE name = ?", (country_name,))
        row = cursor.fetchone()
        if row:
            return row[0]
        
        cursor = conn.execute("INSERT INTO countries (name, code) VALUES (?, ?)", (country_name, code))
        return cursor.lastrowid
    
    def get_or_create_city(self, conn, city_name: str, country_name: str) -> int:
        """Get city ID, creating if necessary"""
        country_id = self.get_or_create_country(conn, country_name)
        
        cursor = conn.execute(
            "SELECT id FROM cities WHERE name = ? AND country_id = ?", 
            (city_name, country_id)
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        
        cursor = conn.execute(
            "INSERT INTO cities (name, country_id) VALUES (?, ?)", 
            (city_name, country_id)
        )
        return cursor.lastrowid
    
    def get_or_create_museum(self, conn, museum_name: str, city_name: str, country_name: str, url: str = None) -> int:
        """Get museum ID, creating if necessary"""
        city_id = self.get_or_create_city(conn, city_name, country_name)
        
        cursor = conn.execute(
            "SELECT id FROM museums WHERE name = ? AND city_id = ?", 
            (museum_name, city_id)
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        
        cursor = conn.execute(
            "INSERT INTO museums (name, city_id, url) VALUES (?, ?, ?)", 
            (museum_name, city_id, url)
        )
        return cursor.lastrowid
    
    def get_or_create_artist(self, conn, artist_name: str) -> Optional[int]:
        """Get artist ID, creating if necessary"""
        if not artist_name or not artist_name.strip():
            return None
            
        artist_name = artist_name.strip()
        normalized = self.normalize_artist_name(artist_name)
        
        if not normalized:
            return None
        
        cursor = conn.execute(
            "SELECT id FROM artists WHERE normalized_name = ?", 
            (normalized,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        
        cursor = conn.execute(
            "INSERT INTO artists (name, normalized_name) VALUES (?, ?)", 
            (artist_name, normalized)
        )
        return cursor.lastrowid
    
    def save_exhibitions(self, exhibitions: List[Exhibition], museum_name: str):
        """Save exhibitions using normalized schema"""
        if not exhibitions:
            print("[DB] No exhibitions to save")
            return
        
        # Get museum info from first exhibition
        first_ex = exhibitions[0]
        museum_city = first_ex.museum_city or "Unknown"
        museum_country = first_ex.museum_country or "Unknown"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            
            # Get or create museum
            museum_id = self.get_or_create_museum(
                conn, museum_name, museum_city, museum_country, first_ex.url
            )
            
            # Clear old exhibitions for this museum
            conn.execute("DELETE FROM exhibitions WHERE museum_id = ?", (museum_id,))
            
            saved_count = 0
            for ex in exhibitions:
                try:
                    # 1) If start/end come as a single range in start_date or end_date, split them.
                    #    We prefer any explicit end date returned by the LLM, but we ALWAYS
                    #    attempt to split ranges so we fill both sides.
                    s_text = ex.start_date
                    e_text = ex.end_date

                    # If start has a range or looks like it, split that
                    if s_text and (re.search(r'\bto\b', s_text, re.IGNORECASE) or any(x in s_text for x in ['–','—',' - '])):
                        s_iso_split, e_iso_split, s_left, e_right = self.parse_date_range_text(s_text)
                        if s_iso_split:
                            ex.start_date = s_left or ex.start_date
                        if e_iso_split:
                            ex.end_date = e_right or ex.end_date

                    # If end contains a range (rare), also split
                    if e_text and (re.search(r'\bto\b', e_text, re.IGNORECASE) or any(x in e_text for x in ['–','—',' - '])):
                        s_iso_split2, e_iso_split2, s_left2, e_right2 = self.parse_date_range_text(e_text)
                        if s_iso_split2 and not ex.start_date:
                            ex.start_date = s_left2
                        if e_iso_split2 and not ex.end_date:
                            ex.end_date = e_right2

                    # 2) If we still only have a single "range-like" string in start (and no end),
                    #    run the splitter once more to fill both.
                    if ex.start_date and not ex.end_date:
                        s_iso_try, e_iso_try, s_left_try, e_right_try = self.parse_date_range_text(ex.start_date)
                        if e_iso_try:
                            ex.end_date = e_right_try

                    # 3) Finally, produce ISO values for persistence
                    start_iso = None
                    end_iso = None

                    # If both present as separate texts, parse separately
                    if ex.start_date:
                        start_iso = self.parse_date_to_iso(ex.start_date)
                    if ex.end_date:
                        end_iso = self.parse_date_to_iso(ex.end_date)

                    # If still missing and we have a range-like original string anywhere, try one last time
                    if (start_iso is None or (end_iso is None and ex.end_date is None)) and (ex.start_date or ex.end_date):
                        s_range = ex.start_date or ex.end_date
                        s_iso_r, e_iso_r, s_left_r, e_right_r = self.parse_date_range_text(s_range)
                        start_iso = start_iso or s_iso_r
                        end_iso   = end_iso   or e_iso_r
                    
                    # Insert exhibition
                    cursor = conn.execute("""
                        INSERT OR IGNORE INTO exhibitions (
                            title, museum_id, start_date_iso, end_date_iso, 
                            start_date_text, end_date_text, details, url, scraped_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ex.title,
                        museum_id,
                        start_iso,
                        end_iso,
                        ex.start_date,
                        ex.end_date,
                        ex.details,
                        ex.url,
                        (ex.scraped_at or datetime.now(UTC)).isoformat()
                    ))
                    
                    exhibition_id = cursor.lastrowid
                    if not exhibition_id:
                        # Exhibition already exists, get its ID
                        cursor = conn.execute(
                            "SELECT id FROM exhibitions WHERE title = ? AND museum_id = ? AND start_date_iso = ?",
                            (ex.title, museum_id, start_iso)
                        )
                        row = cursor.fetchone()
                        if row:
                            exhibition_id = row[0]
                    
                    if exhibition_id:
                        # Handle main artist
                        if ex.main_artist:
                            artist_id = self.get_or_create_artist(conn, ex.main_artist)
                            if artist_id:
                                conn.execute("""
                                    INSERT OR IGNORE INTO exhibition_artists (exhibition_id, artist_id, role)
                                    VALUES (?, ?, 'main')
                                """, (exhibition_id, artist_id))
                        
                        # Handle other artists
                        if ex.other_artists:
                            for artist_name in ex.other_artists:
                                if artist_name and artist_name.strip():
                                    artist_id = self.get_or_create_artist(conn, artist_name.strip())
                                    if artist_id:
                                        conn.execute("""
                                            INSERT OR IGNORE INTO exhibition_artists (exhibition_id, artist_id, role)
                                            VALUES (?, ?, 'featured')
                                        """, (exhibition_id, artist_id))
                        
                        # Update FTS table if it exists
                        try:
                            # Get all artist names for this exhibition
                            cursor = conn.execute("""
                                SELECT GROUP_CONCAT(a.name, ' ')
                                FROM exhibition_artists ea
                                JOIN artists a ON a.id = ea.artist_id
                                WHERE ea.exhibition_id = ?
                            """, (exhibition_id,))
                            artist_names = cursor.fetchone()[0] or ""
                            
                            conn.execute("""
                                INSERT OR REPLACE INTO exhibitions_fts(rowid, title, details, artist_names)
                                VALUES (?, ?, ?, ?)
                            """, (exhibition_id, ex.title, ex.details or "", artist_names))
                        except sqlite3.OperationalError:
                            # FTS not available, skip
                            pass
                        
                        saved_count += 1
                        
                except Exception as e:
                    print(f"[DB] Error saving exhibition '{ex.title}': {e}")
                    continue
        
        # Update museum status
        self.update_museum_status(museum_name, "success", saved_count)
        
        # Export to JSON
        self._export_to_json()
        print(f"[DB] Saved {saved_count} exhibitions for {museum_name}")
    
    def get_museums_to_scrape(self, days_old: int = 90) -> List[Museum]:
        """Get museums that need scraping"""
        cutoff_date = datetime.now(UTC).timestamp() - (days_old * 24 * 60 * 60)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    m.id,
                    m.name,
                    c.name as city_name,
                    co.name as country_name,
                    m.url,
                    m.last_scraped,
                    m.scrape_status,
                    m.exhibition_count
                FROM museums m
                JOIN cities c ON m.city_id = c.id
                JOIN countries co ON c.country_id = co.id
                WHERE m.last_scraped IS NULL 
                   OR m.last_scraped < datetime(?, 'unixepoch')
                ORDER BY m.last_scraped ASC
            """, (cutoff_date,))
            
            museums = []
            for row in cursor:
                museums.append(Museum(
                    id=row['id'],
                    name=row['name'],
                    city_name=row['city_name'],
                    country_name=row['country_name'],
                    url=row['url'],
                    last_scraped=datetime.fromisoformat(row['last_scraped']) if row['last_scraped'] else None,
                    scrape_status=row['scrape_status'],
                    exhibition_count=row['exhibition_count']
                ))
            return museums
    
    def update_museum_status(self, museum_name: str, status: str, exhibition_count: int = 0, error: str = None):
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
    
    def search_exhibitions_by_city(self, city_name: str, current_only: bool = True) -> List[Dict]:
        """Find all exhibitions in a city - perfect for travel planning"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = """
                SELECT 
                    e.title,
                    e.start_date_text,
                    e.end_date_text,
                    e.start_date_iso,
                    e.end_date_iso,
                    e.details,
                    e.url,
                    m.name as museum_name,
                    c.name as museum_city,
                    co.name as museum_country,
                    GROUP_CONCAT(DISTINCT a.name) as artists
                FROM exhibitions e
                JOIN museums m ON e.museum_id = m.id
                JOIN cities c ON m.city_id = c.id
                JOIN countries co ON c.country_id = co.id
                LEFT JOIN exhibition_artists ea ON e.id = ea.exhibition_id
                LEFT JOIN artists a ON ea.artist_id = a.id
                WHERE LOWER(c.name) = LOWER(?)
            """
            
            if current_only:
                query += " AND (e.end_date_iso IS NULL OR e.end_date_iso >= date('now'))"
            
            query += " GROUP BY e.id ORDER BY e.start_date_iso"
            
            cursor = conn.execute(query, (city_name,))
            return [dict(row) for row in cursor]
    
    def search_exhibitions_by_artist(self, artist_name: str, current_only: bool = True) -> List[Dict]:
        """Find all exhibitions featuring an artist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = """
                SELECT 
                    e.title,
                    e.start_date_text,
                    e.end_date_text,
                    e.start_date_iso,
                    e.end_date_iso,
                    e.details,
                    e.url,
                    m.name as museum_name,
                    c.name as museum_city,
                    co.name as museum_country,
                    a.name as main_artist,
                    ea.role as artist_role
                FROM exhibitions e
                JOIN exhibition_artists ea ON e.id = ea.exhibition_id
                JOIN artists a ON ea.artist_id = a.id
                JOIN museums m ON e.museum_id = m.id
                JOIN cities c ON m.city_id = c.id
                JOIN countries co ON c.country_id = co.id
                WHERE a.normalized_name LIKE LOWER(?)
            """
            
            if current_only:
                query += " AND (e.end_date_iso IS NULL OR e.end_date_iso >= date('now'))"
            
            query += " ORDER BY e.start_date_iso"
            
            # Use normalized search
            search_term = f"%{self.normalize_artist_name(artist_name)}%"
            cursor = conn.execute(query, (search_term,))
            return [dict(row) for row in cursor]
    
    def get_travel_destinations(self, months_ahead: int = 6) -> List[Dict]:
        """Get cities ranked by upcoming exhibitions - perfect for travel planning!"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            cursor = conn.execute("""
                SELECT 
                    c.name as city,
                    co.name as country,
                    COUNT(e.id) as exhibition_count,
                    COUNT(DISTINCT m.id) as museum_count,
                    MIN(e.start_date_iso) as earliest_exhibition,
                    MAX(e.end_date_iso) as latest_exhibition
                FROM cities c
                JOIN countries co ON c.country_id = co.id
                JOIN museums m ON m.city_id = c.id
                JOIN exhibitions e ON e.museum_id = m.id
                WHERE 
                    (e.end_date_iso IS NULL OR e.end_date_iso >= date('now'))
                    AND (e.start_date_iso IS NULL OR e.start_date_iso <= date('now', '+{} months'))
                GROUP BY c.id, co.id
                ORDER BY exhibition_count DESC
            """.format(months_ahead))
            
            return [dict(row) for row in cursor]
    
    def search_exhibitions(self, city: str = None, country: str = None, 
                         artist: str = None, current_only: bool = True) -> List[Dict]:
        """Legacy method updated to use new schema"""
        if city:
            return self.search_exhibitions_by_city(city, current_only)
        elif artist:
            return self.search_exhibitions_by_artist(artist, current_only)
        else:
            # General search
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                query = """
                    SELECT 
                        e.title,
                        e.start_date_text as start_date,
                        e.end_date_text as end_date,
                        e.details,
                        e.url,
                        m.name as museum_name,
                        c.name as museum_city,
                        co.name as museum_country,
                        GROUP_CONCAT(DISTINCT a.name) as main_artist
                    FROM exhibitions e
                    JOIN museums m ON e.museum_id = m.id
                    JOIN cities c ON m.city_id = c.id
                    JOIN countries co ON c.country_id = co.id
                    LEFT JOIN exhibition_artists ea ON e.id = ea.exhibition_id
                    LEFT JOIN artists a ON ea.artist_id = a.id
                    WHERE 1=1
                """
                
                params = []
                if country:
                    query += " AND LOWER(co.name) = LOWER(?)"
                    params.append(country)
                
                if current_only:
                    query += " AND (e.end_date_iso IS NULL OR e.end_date_iso >= date('now'))"
                
                query += " GROUP BY e.id ORDER BY e.start_date_iso"
                
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor]
    
    def get_cities_with_exhibitions(self) -> List[Dict[str, Any]]:
        """Get cities with current exhibition counts"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    c.name as city,
                    co.name as country,
                    COUNT(e.id) as exhibition_count,
                    COUNT(DISTINCT m.id) as museum_count
                FROM cities c
                JOIN countries co ON c.country_id = co.id
                JOIN museums m ON m.city_id = c.id
                JOIN exhibitions e ON e.museum_id = m.id
                WHERE e.end_date_iso IS NULL OR e.end_date_iso >= date('now')
                GROUP BY c.id, co.id
                ORDER BY exhibition_count DESC
            """)
            
            return [dict(row) for row in cursor]
    
    def _export_to_json(self):
        """Export all current exhibitions to JSON file"""
        try:
            exhibitions = self.search_exhibitions(current_only=False)
            
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(exhibitions, f, indent=2, ensure_ascii=False, default=str)
            
            print(f"[DB] Exported {len(exhibitions)} exhibitions to {self.json_path}")
        except Exception as e:
            print(f"[DB] Error exporting to JSON: {e}")
    
    def import_museums_from_csv(self, csv_path: str):
        """Import museums from CSV file using new schema"""
        import csv
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                count = 0
                for row in reader:
                    self.get_or_create_museum(
                        conn,
                        row['museum'].strip(),
                        row['city'].strip(),
                        row['country'].strip(),
                        row['url'].strip()
                    )
                    count += 1
                        
        print(f"[DB] Imported {count} museums from {csv_path}")
    
    def _norm_dash(self, s: str) -> str:
        return (s or "").replace("–", "-").replace("—", "-").strip()

    def _month_num(self, name: str) -> str:
        month_map = {
            'january': '01','february': '02','march': '03','april': '04','may': '05','june': '06',
            'july': '07','august': '08','september': '09','october': '10','november': '11','december': '12'
        }
        return month_map.get((name or "").lower())

    def _parse_single_date(self, s: str, fallback_year: str = None, fallback_month: str = None) -> Optional[str]:
        """
        Parse a single date fragment into ISO (YYYY-MM-DD).
        Fills missing year/month from fallbacks when present.
        Tries multiple strategies; returns None if unknown.
        """
        if not s: return None
        s = s.strip()

        # If we have fallback parts, prepend/append to help parser
        candidate = s
        # If there's a day + month but no year, append year
        if fallback_year and re.search(r"\b(\d{1,2})\b", s) and re.search(r"[A-Za-z]+", s) and not re.search(r"\b\d{4}\b", s):
            candidate = f"{s} {fallback_year}"
        # If there's only a day and fallback month/year available (e.g. "1" with "January 2026")
        if fallback_month and fallback_year and re.fullmatch(r"\d{1,2}", s):
            candidate = f"{s} {fallback_month} {fallback_year}"

        # Try dateutil (prefer day-first for dotted/slashed)
        try:
            from dateutil import parser as dateparse
            # dayfirst=True improves "05.09.2025", "16/04/2026" etc.
            dt = dateparse.parse(candidate, fuzzy=True, dayfirst=True)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        # Manual: "2 August 2025" / "2nd August 2025"
        m = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})', candidate)
        if m:
            d, mon, y = m.groups()
            mon_num = self._month_num(mon)
            if mon_num: return f"{y}-{mon_num}-{d.zfill(2)}"

        # Manual: "August 2025" (assume first of month)
        m = re.search(r'([A-Za-z]+)\s+(\d{4})', candidate)
        if m:
            mon, y = m.groups()
            mon_num = self._month_num(mon)
            if mon_num: return f"{y}-{mon_num}-01"

        # Manual: "05.09.2025" or "05/09/2025" or "05-09-2025"
        m = re.search(r'\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b', candidate)
        if m:
            d, mon, y = m.groups()
            if len(y) == 2:
                y = "20" + y  # assume 20xx
            return f"{y}-{str(mon).zfill(2)}-{str(d).zfill(2)}"

        return None

    def parse_date_range_text(self, date_text: str) -> (Optional[str], Optional[str], Optional[str], Optional[str]):
        """
        Given a free-form date_text that may contain a range, return:
        (start_iso, end_iso, start_text, end_text)

        Handles:
          - "2 August 2025 - 25 January 2026"
          - "1-31 January 2026" (same month/year)
          - "From 05.09.2025 to 12.10.2025"
          - "27 June - 8 November 2026" (left inherits year)
          - "16 April – 19 July 2026"  (left inherits year)
          - "Opens 26 June 2025" (start only)
        """
        if not date_text:
            return None, None, None, None

        s = self._norm_dash(date_text)
        s_low = s.lower()

        # Remove fluff words but keep structure
        s_clean = re.sub(r'\b(opens|opening|from)\b', '', s_low, flags=re.IGNORECASE).strip()
        s_clean = re.sub(r'\s{2,}', ' ', s_clean)

        # If we see a clear "to"
        if re.search(r'\bto\b', s_clean):
            parts = re.split(r'\bto\b', s_clean, maxsplit=1, flags=re.IGNORECASE)
        else:
            # Split on first dash used as range marker
            parts = re.split(r'\s-\s| - |–|-', s, maxsplit=1)

        if len(parts) == 2:
            left, right = parts[0].strip(), parts[1].strip()

            # Try to extract fallback month/year from right part
            # e.g., right="8 November 2026" -> month="November", year="2026"
            right_year = None
            right_month_name = None
            m = re.search(r'([A-Za-z]+)\s+\d{1,2}\s*,?\s*(\d{4})', right)
            if m:
                right_month_name, right_year = m.groups()
            else:
                m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s*(\d{4})', right)
                if m:
                    _, right_month_name, right_year = m.groups()
                else:
                    # dotted numeric right may contain year
                    m = re.search(r'\b\d{1,2}[./-]\d{1,2}[./-](\d{2,4})\b', right)
                    if m:
                        y = m.group(1)
                        right_year = "20" + y if len(y) == 2 else y

            right_month_num = self._month_num(right_month_name) if right_month_name else None

            start_iso = self._parse_single_date(left, fallback_year=right_year, fallback_month=right_month_name)
            end_iso = self._parse_single_date(right)

            # Special compact pattern like "1-31 January 2026"
            if not end_iso and re.search(r'^\d{1,2}\s*-\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}$', s):
                m2 = re.search(r'^(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', s)
                if m2:
                    d1, d2, mon, y = m2.groups()
                    mon_num = self._month_num(mon)
                    if mon_num:
                        start_iso = f"{y}-{mon_num}-{str(d1).zfill(2)}"
                        end_iso   = f"{y}-{mon_num}-{str(d2).zfill(2)}"

            return start_iso, end_iso, left, right

        # Not a range → try single start (e.g., "Opens 26 June 2025")
        start_iso = self._parse_single_date(s_clean)
        return start_iso, None, s, None
