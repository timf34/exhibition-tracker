### v0.1 

- Good as a first go 
- Duplicate data 
	- Ok this version of the script works well enough, however it double saves the ehxbitions... it saves them all once on the homepage, and then saves them again once it clicks into them 
and adds more info such as the names of the artists and such. 
- Data not standardized 
	- The script will sometimes fill the "artists" tag with every single artist it finds. We would want to differentiate between the main artist, and other artists who's work is included.
	- The script will also include the artists birth and death year - we might want to use Pydantic or something to make sure its just their normal name as a strict string. 
	- For example: `"artists": ["William Blake (1757-1827)", "James Barry (1741–1806)", "Henry Fuseli (1741–1825)", etc.`