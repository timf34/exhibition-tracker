## Conosle logs for different version 

### v0.1 in headless mode:

```
PS C:\Users\timf3\VSCode\exhibition-tracker> uv run python exhibitions.py
INFO     [service] Using anonymized telemetry, see https://docs.browser-use.com/development/telemetry.
Scraping exhibitions from: https://www.nationalgallery.ie/art-and-artists/exhibitions
INFO     [Agent] 🔗 Found URL in task: https://www.nationalgallery.ie/art-and-artists/exhibitions, adding as initial action...
INFO     [Agent] 🚀 Task:
                    Visit https://www.nationalgallery.ie/art-and-artists/exhibitions and find all current and upcoming exhibitions.

                    For each exhibition, extract:
                    - Title (required)
                    - Artist name(s) if available (pass as comma-separated string for multiple artists)
                    - Start date if available
                    - End date if available
INFO     [Agent] 🚀 Task:
                    Visit https://www.nationalgallery.ie/art-and-artists/exhibitions and find all current and upcoming exhibitions.

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
INFO     [Agent] 🚀 Task:
                    Visit https://www.nationalgallery.ie/art-and-artists/exhibitions and find all current and upcoming exhibitions.

                    For each exhibition, extract:
                    - Title (required)
                    - Artist name(s) if available (pass as comma-separated string for multiple artists)
                    - Start date if available
                    - End date if available
                    - Museum name (try to find it on the page)
                    - Brief details/summary (optional - only if easily visible)
                    - Direct URL link to the exhibition if available

                    Visit https://www.nationalgallery.ie/art-and-artists/exhibitions and find all current and upcoming exhibitions.

                    For each exhibition, extract:
                    - Title (required)
                    - Artist name(s) if available (pass as comma-separated string for multiple artists)
                    - Start date if available
                    - End date if available
                    For each exhibition, extract:
                    - Title (required)
                    - Artist name(s) if available (pass as comma-separated string for multiple artists)
                    - Start date if available
                    - End date if available
                    - Artist name(s) if available (pass as comma-separated string for multiple artists)
                    - Start date if available
                    - End date if available
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

INFO     [service] ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
INFO     [service] 🔐 To view this run in Browser Use Cloud, authenticate with:
INFO     [service]     👉  browser-use auth
INFO     [service]     or: python -m browser_use.cli auth
INFO     [service] ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

INFO     [Agent]   🦾 [ACTION 1/1] go_to_url: url: https://www.nationalgallery.ie/art-and-artists/exhibitions, new_tab: False
INFO     [tools] 🔗 Navigated to https://www.nationalgallery.ie/art-and-artists/exhibitions
INFO     [Agent]

INFO     [Agent] 📍 Step 1:
ERROR    [Agent] ❌ Result failed 1/4 times:
 ("1 validation error for AgentOutput\n  Invalid JSON: EOF while parsing a value at line 1 column 0 [type=json_invalid, input_value='', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.11/v/json_invalid", 502)
INFO     [Agent]

INFO     [Agent] 📍 Step 2:
INFO     [Agent]   👍 Eval: Success — page loaded to the target exhibitions URL (https://www.nationalgallery.ie/art-and-artists/exhibitions).
INFO     [Agent]   🎯 Next goal: Accept cookies to remove the banner, create a todo.md plan file for the extraction steps, then scroll down the page to reveal more exhibition listings so I can click into each exhibition and save data.
INFO     [Agent]   🦾 [ACTION 1/3] click_element_by_index: index: 12, while_holding_ctrl: False
INFO     [tools] 🖱️ Clicked element
INFO     [Agent]   🦾 [ACTION 2/3] write_file: file_name: todo.md, content: # National Gallery Ireland — Exhibitions Extraction Plan\n\n## Goal: Collect current and
INFO     [tools] 💾 Data written to file todo.md successfully.
INFO     [Agent]   🦾 [ACTION 3/3] scroll: down: True, num_pages: 1.0, frame_element_index: None
INFO     [tools] 🔍 Scrolled down the page by one page
INFO     [Agent] 

INFO     [Agent] 📍 Step 3:
INFO     [Agent]   👍 Eval: Success — page loaded and scrolled; cookie banner handled earlier and todo.md was created. Verdict: Success.
INFO     [Agent]   🎯 Next goal: Open the detail pages for the primary current/upcoming and early-2026 exhibitions in background tabs so I can extract their details in following steps.
INFO     [Agent]   🦾 [ACTION 1/10] click_element_by_index: index: 17, while_holding_ctrl: True
WARNING  [BrowserSession] No visible quad found, using first quad
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 2/10] click_element_by_index: index: 18, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 3/10] click_element_by_index: index: 19, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 4/10] click_element_by_index: index: 21, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [service] Page changed after action: actions click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index are not yet executed
INFO     [Agent] 

INFO     [Agent] 📍 Step 4:
INFO     [Agent]   👍 Eval: Partial success — exhibition detail tabs were opened, but some click actions may not have executed; relevant tabs (Maurice Marinot, Créatúir na Cartlainne, Picasso) are available to inspect.
INFO     [Agent]   🎯 Next goal: Switch to the Maurice Marinot exhibition tab (tab id ending 1C4D) so I can extract its title, artist(s), start/end dates, museum name, summary, and URL and then save it.
INFO     [Agent]   🦾 [ACTION 1/1] switch_tab: tab_id: 1C4D
INFO     [tools] 🔄  Switched to Tab with ID 1C4D
INFO     [Agent] 

INFO     [Agent] 📍 Step 5:
INFO     [Agent]   👍 Eval: Success — switched to Maurice Marinot exhibition tab (tab 1C4D) and page content is visible for extraction.
INFO     [Agent]   🎯 Next goal: Save the Maurice Marinot exhibition data with save_exhibition_data, then switch to the Créatúir na Cartlainne tab (35D6) to extract the next exhibition.
INFO     [Agent]   🦾 [ACTION 1/2] save_exhibition_data: title: Maurice Marinot – On Paper, In Glass, artists: Maurice Marinot, start_date: 2 August 2025, end
INFO     [Agent]   🦾 [ACTION 2/2] switch_tab: tab_id: 35D6
INFO     [tools] 🔄  Switched to Tab with ID 35D6
INFO     [Agent] 

INFO     [Agent] 📍 Step 6:
INFO     [Agent]   👍 Eval: Success — switched to the Créatúir na Cartlainne exhibition tab (35D6) and page content is visible for extraction.
INFO     [Agent]   🎯 Next goal: Save the Créatúir na Cartlainne exhibition data with save_exhibition_data, then switch to the Picasso tab (3BE3) to extract the next exhibition.
INFO     [Agent]   🦾 [ACTION 1/2] save_exhibition_data: title: Créatúir na Cartlainne | Tails from the Archive, artists: , start_date: 26 June 2025, end_date
INFO     [Agent]   🦾 [ACTION 2/2] switch_tab: tab_id: 3BE3
INFO     [tools] 🔄  Switched to Tab with ID 3BE3
INFO     [Agent] 

INFO     [Agent] 📍 Step 7:
INFO     [Agent]   👍 Eval: Success — switched to the Picasso exhibition tab and page content is visible for extraction.
INFO     [Agent]   🎯 Next goal: Save the Picasso exhibition using save_exhibition_data with title, artist, dates, museum, summary, and URL, then switch back to the main exhibitions tab to continue.
INFO     [Agent]   🦾 [ACTION 1/2] save_exhibition_data: title: Picasso: From the Studio, artists: Pablo Picasso, start_date: 9 October 2025, end_date: 22 F
INFO     [Agent]   🦾 [ACTION 2/2] switch_tab: tab_id: 2B72
INFO     [tools] 🔄  Switched to Tab with ID 2B72
INFO     [Agent] 

INFO     [Agent] 📍 Step 8:
INFO     [Agent]   👍 Eval: Success — switched back to the main exhibitions tab (2B72) and the main page with upcoming exhibitions is visible.
INFO     [Agent]   🎯 Next goal: Open the upcoming and 'Coming in 2026' exhibition links (indices 23, 24, 25, 26, 27, 28) in background tabs so I can extract and save each exhibition's details in following steps.
INFO     [Agent]   🦾 [ACTION 1/6] click_element_by_index: index: 23, while_holding_ctrl: True
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 2/6] click_element_by_index: index: 24, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 3/6] click_element_by_index: index: 25, while_holding_ctrl: True
WARNING  [BrowserSession] No visible quad found, using first quad
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [service] Something new appeared after action 3 / 6: actions click_element_by_index, click_element_by_index, click_element_by_index were not executed
INFO     [Agent] 

INFO     [Agent] 📍 Step 9:
INFO     [Agent]   👍 Eval: Previous goal: open upcoming/2026 exhibition links in background tabs — partially successful (some clicks opened, some did not). Verdict: Partial success.
INFO     [Agent]   🎯 Next goal: Open the detail pages for the 'Coming in 2026' exhibitions (indices 23–28) in background tabs so I can extract their data on the next steps.
INFO     [Agent]   🦾 [ACTION 1/6] click_element_by_index: index: 23, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [service] Page changed after action: actions click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index are not yet executed
INFO     [Agent] 

INFO     [Agent] 📍 Step 10:
INFO     [Agent]   👍 Eval: Partial success — some upcoming exhibition links were opened in background tabs earlier, but several clicks did not execute; need to open the remaining detail pages.
INFO     [Agent]   🎯 Next goal: Open the remaining 'Coming in 2026' and upcoming exhibition detail pages by ctrl-clicking the visible exhibition links (indices 22, 23, 25, 26, 27, 28, 29) so I can extract and save each exhibition's details in following steps.
INFO     [Agent]   🦾 [ACTION 1/7] click_element_by_index: index: 22, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [service] Page changed after action: actions click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index, click_element_by_index are not yet executed
INFO     [Agent] 

INFO     [Agent] 📍 Step 11:
INFO     [Agent]   👍 Eval: Partial success — some exhibition detail pages were opened earlier, but several click actions to open the remaining 'Coming in 2026' links did not execute.
INFO     [Agent]   🎯 Next goal: Open the remaining 'Coming in 2026' exhibition links (indices 23,24,25,26,27,28,29) in background tabs so I can extract and save their details.
INFO     [Agent]   🦾 [ACTION 1/7] click_element_by_index: index: 23, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 2/7] click_element_by_index: index: 24, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 3/7] click_element_by_index: index: 25, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 4/7] click_element_by_index: index: 26, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 5/7] click_element_by_index: index: 27, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 6/7] click_element_by_index: index: 28, while_holding_ctrl: True
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent]   🦾 [ACTION 7/7] click_element_by_index: index: 29, while_holding_ctrl: True
INFO     [BrowserSession] 🔗 New tab opened - switching to it
INFO     [tools] 🖱️ Clicked element and opened in new tab
INFO     [Agent] 

INFO     [Agent] 📍 Step 12:
INFO     [Agent]   👍 Eval: Success — main exhibitions page visible and required exhibition detail tabs were opened; ready to save additional exhibitions from their tabs.
INFO     [Agent]   🎯 Next goal: Switch to each exhibition tab (9516, 33AC, 3F7F, AB0D, 6B19) and save their exhibition data using save_exhibition_data.
INFO     [Agent]   🦾 [ACTION 1/10] switch_tab: tab_id: 9516
INFO     [tools] 🔄  Switched to Tab with ID 9516
INFO     [Agent]   🦾 [ACTION 2/10] save_exhibition_data: title: William Blake: The Age of Romantic Fantasy, artists: , start_date: 16 April 2026, end_date:
INFO     [Agent]   🦾 [ACTION 3/10] switch_tab: tab_id: 33AC
INFO     [tools] 🔄  Switched to Tab with ID 33AC
INFO     [Agent]   🦾 [ACTION 4/10] save_exhibition_data: title: Turner as Inspiration, artists: , start_date: 1 January 2026, end_date: 31 January 2026, m
INFO     [Agent]   🦾 [ACTION 5/10] switch_tab: tab_id: 3F7F
INFO     [tools] 🔄  Switched to Tab with ID 3F7F
INFO     [Agent]   🦾 [ACTION 6/10] save_exhibition_data: title: From Rembrandt to Matisse – A Celebration of European Prints and Drawings, artists: , start_date:
INFO     [Agent]   🦾 [ACTION 7/10] switch_tab: tab_id: AB0D
INFO     [tools] 🔄  Switched to Tab with ID AB0D
INFO     [Agent]   🦾 [ACTION 8/10] save_exhibition_data: title: Hilma af Klint: Artist and Visionary, artists: Hilma af Klint, start_date: 15 October 2026, en
INFO     [Agent]   🦾 [ACTION 9/10] switch_tab: tab_id: 6B19
INFO     [tools] 🔄  Switched to Tab with ID 6B19
INFO     [Agent]   🦾 [ACTION 10/10] save_exhibition_data: title: AIB Young Portrait Prize 2026, artists: , start_date: 14 November 2026, end_date: 14 March 2
INFO     [Agent] 

INFO     [Agent] 📍 Step 13:
INFO     [Agent]   👍 Eval: Success — switched to tab 6B19 (AIB Young Portrait Prize 2026) and the page is visible for extraction.
INFO     [Agent]   🎯 Next goal: Save the AIB Young Portrait Prize 2026 exhibition from the current tab, then switch to tab 1336 to extract and save the next exhibition.
INFO     [Agent]   🦾 [ACTION 1/2] save_exhibition_data: title: AIB Young Portrait Prize 2026, artists: , start_date: 14 November 2026, end_date: 14 March 2
INFO     [Agent]   🦾 [ACTION 2/2] switch_tab: tab_id: 1336
INFO     [tools] 🔄  Switched to Tab with ID 1336
INFO     [Agent] 

INFO     [Agent] 📍 Step 14:
INFO     [Agent]   👍 Eval: Success — current tab 1336 is AIB Portrait Prize 2026 and its page is visible for extraction.
INFO     [Agent]   🎯 Next goal: Save the AIB Portrait Prize 2026 exhibition using save_exhibition_data, then switch to the Jan Steen tab (0290) to extract and save its data.
INFO     [Agent]   🦾 [ACTION 1/2] save_exhibition_data: title: AIB Portrait Prize 2026, artists: , start_date: 14 November 2026, end_date: 14 March 2027
INFO     [Agent]   🦾 [ACTION 2/2] switch_tab: tab_id: 0290
INFO     [tools] 🔄  Switched to Tab with ID 0290
INFO     [Agent] 

INFO     [Agent] 📍 Step 15:
INFO     [Agent]   👍 Eval: Partial success — many exhibition detail pages were opened and several exhibitions were saved, but at least one visible exhibition (Jan Steen) has not yet been saved so the extraction is not fully complete.
INFO     [Agent]   🎯 Next goal: If allowed to continue, switch to the Jan Steen tab, call save_exhibition_data for it, then iterate through the remaining open exhibition tabs and save each exhibition's data until all current and upcoming exhibitions on the page are saved.
INFO     [Agent]   🦾 [ACTION 1/1] text='Summary of progress and data found so far (task incomplete — success=false):\n\nTask requested: Visit https://www.nationalgallery.ie/art-and-artists/exhibitions and find all current and upcoming exhibitions; for each extract title, artist(s) if available, start date, end date, museum, brief details (if visible), and direct URL, and save each with save_exhibition_data.\n\nWhat I have already saved (via save_exhibition_data) and relevant details obtained during the session:\n1) Maurice Marinot – On Paper, In Glas...
INFO     [Agent]
📄  Final Result:
Summary of progress and data found so far (task incomplete — success=false):

Task requested: Visit https://www.nationalgallery.ie/art-and-artists/exhibitions and find all current and upcoming exhibitions; for each extract title, artist(s) if available, start date, end date, museum, brief details (if visible), and direct URL, and save each with save_exhibition_data.

What I have already saved (via save_exhibition_data) and relevant details obtained during the session:
1) Maurice Marinot – On Paper, In Glass
   - Artists: Maurice Marinot
   - Dates: 2 August 2025 – 25 January 2026
   - Museum / Location: Sir Hugh Lane Room (National Gallery of Ireland)
   - URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/maurice-marinot-paper-glass
   - Notes: Summary saved when processed.

2) Créatúir na Cartlainne | Tails from the Archive
   - Artists: (not specified on page)
   - Dates: Opening 26 June 2025 (end date not explicitly visible)
   - Museum / Location: Room 11 (National Gallery of Ireland)
   - URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/creatuir-na-cartlainne-tails-archive
   - Notes: Descriptive summary visible on page; saved.

3) Picasso: From the Studio
   - Artists: Pablo Picasso (implied by title)
   - Dates: 9 October 2025 – 22 February 2026
   - Museum / Location: Beit Wing (Rooms 6-10) (National Gallery of Ireland)
   - URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/picasso-studio
   - Notes: Saved.

4) William Blake: The Age of Romantic Fantasy
   - Artists: William Blake (implied by title)
   - Dates: (not captured in agent history text)
   - Museum / Location: (National Gallery of Ireland)
   - URL: (tab opened to the William Blake detail page)
   - Notes: Saved via save_exhibition_data earlier in the session.

5) Turner as Inspiration
   - Artists: (Turner-related exhibition)
   - Dates: (not captured in agent history text)
   - Museum / Location: (National Gallery of Ireland)
   - URL: (tab opened)
   - Notes: Saved.

6) From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   - Artists: (various)
   - Dates: (not captured in agent history text)
   - Museum / Location: (National Gallery of Ireland)
   - URL: (tab opened)
   - Notes: Saved.

7) Hilma af Klint: Artist and Visionary
   - Artists: Hilma af Klint
   - Dates: (not captured in agent history text)
   - Museum / Location: (National Gallery of Ireland)
   - URL: (tab opened)
   - Notes: Saved.

8) AIB Young Portrait Prize 2026
   - Artists: (jury/entrants; not a single artist)
   - Dates: 14 November 2026 – 14 March 2027 (captured in history)
   - Museum / Location: (National Gallery of Ireland)
   - URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/aib-young-portrait-prize-2026
   - Notes: Saved.

9) AIB Portrait Prize 2026
   - Artists: (multiple; competition)
   - Dates: (not captured in agent history text)
   - Museum / Location: (National Gallery of Ireland)
   - URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/aib-portrait-prize-2026
   - Notes: Saved.

Open/current tab (visible now) that has not yet been saved:
- Jan Steen: Sacred and Profane
  - Artists: Jan Steen (1626–1679)
  - Dates: 21 November 2026 – 25 April 2027 (visible on the page)
  - Museum / Location: Sir Hugh Lane Room (National Gallery of Ireland)
  - URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/jan-steen-sacred-and-profane
  - Notes: Descriptive summary visible on the page; this page is currently open but save_exhibition_data has not been recorded in the session for it.

Other notes about session state and remaining work:
- Multiple exhibition detail tabs were opened during the session (tab list includes IDs for William Blake, Maurice Marinot, Créatúir na Cartlainne, Picasso, Turner, From Rembrandt to Matisse, Hilma af Klint, AIB Young Portrait Prize 2025/2026 and others). Several were saved; at least Jan Steen is open and not saved yet.
- The todo.md planning file was created during the session and lists tasks to process and save exhibitions. It guided the extraction.
- Because the user asked that each exhibition be saved with save_exhibition_data, and there remain at least one open/current exhibition (Jan Steen) that has not been saved yet (and possibly other open tabs whose details were not fully captured in the history), I cannot mark the task fully complete.

Remaining steps to finish the user's request (if you want me to continue):
1) Save Jan Steen: Sacred and Profane using save_exhibition_data (include title, artists="Jan Steen", start date 21 November 2026, end date 25 April 2027, museum="National Gallery of Ireland / Sir Hugh Lane Room", summary from page, and URL).
2) Iterate through any remaining open exhibition tabs (and any exhibitions still listed on the main exhibitions page) and call save_exhibition_data for each one not yet saved. Confirm dates/artist names on each detail page while saving.
3) Final check to ensure every current, upcoming, and featured exhibition from the exhibitions listing has been saved.

Conclusion: I have saved nine exhibitions so far and opened multiple detail pages; however the extraction is not fully finished (Jan Steen is open but not saved and there may be other remaining items). Therefore I set success = false. If you want, I can continue now and finish saving the remaining exhibitions (I will switch to the current Jan Steen tab, save it, then process remaining tabs and confirm completion).


INFO     [Agent] ❌ Task completed without success
WARNING  [cdp_use.client] WebSocket connection closed: no close frame received or sent

Found 10 exhibitions:
================================================================================
1. Maurice Marinot – On Paper, In Glass
   Artists: Maurice Marinot
   Dates: 2 August 2025 - 25 January 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/maurice-marinot-paper-glass
   Details: An in-focus exhibition showcasing a selection of Maurice Marinot's works spanning the 1900s to the 1...

2. Créatúir na Cartlainne | Tails from the Archive
   Dates: 26 June 2025 - TBD
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/creatuir-na-cartlainne-tails-archive
   Details: Celebrates our relationship with animals – as a source of joy, humour, awe, inspiration and companio...

3. Picasso: From the Studio
   Artists: Pablo Picasso
   Dates: 9 October 2025 - 22 February 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/picasso-studio
   Details: A major monographic exhibition exploring Pablo Picasso's studios and the influence of his working sp...

4. William Blake: The Age of Romantic Fantasy
   Dates: 16 April 2026 - 19 July 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/william-blake-age-romantic-fantasy

5. Turner as Inspiration
   Dates: 1 January 2026 - 31 January 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/viva-europa-european-works-paper

7. Hilma af Klint: Artist and Visionary
   Artists: Hilma af Klint
   Dates: 15 October 2026 - 7 February 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/hilma-af-klint

8. AIB Young Portrait Prize 2026
   Dates: 14 November 2026 - 14 March 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/aib-young-portrait-prize-2026

9. AIB Young Portrait Prize 2026
   Dates: 14 November 2026 - 14 March 2027
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/viva-europa-european-works-paper

7. Hilma af Klint: Artist and Visionary
   Artists: Hilma af Klint
   Dates: 15 October 2026 - 7 February 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/hilma-af-klint

8. AIB Young Portrait Prize 2026
   Dates: 14 November 2026 - 14 March 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/aib-young-portrait-prize-2026

9. AIB Young Portrait Prize 2026
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/viva-europa-european-works-paper

7. Hilma af Klint: Artist and Visionary
   Artists: Hilma af Klint
   Dates: 15 October 2026 - 7 February 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/hilma-af-klint

8. AIB Young Portrait Prize 2026
   Dates: 14 November 2026 - 14 March 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/viva-europa-european-works-paper

7. Hilma af Klint: Artist and Visionary
   Artists: Hilma af Klint
   Dates: 15 October 2026 - 7 February 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/hilma-af-klint
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/viva-europa-european-works-paper

7. Hilma af Klint: Artist and Visionary
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/viva-europa-european-works-paper
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/turner-inspiration

6. From Rembrandt to Matisse – A Celebration of European Prints and Drawings
   Dates: 27 June 2026 - 8 November 2026
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/viva-europa-european-works-paper

7. Hilma af Klint: Artist and Visionary
   Artists: Hilma af Klint
   Dates: 15 October 2026 - 7 February 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/hilma-af-klint

8. AIB Young Portrait Prize 2026
   Dates: 14 November 2026 - 14 March 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/aib-young-portrait-prize-2026

9. AIB Young Portrait Prize 2026
   Dates: 14 November 2026 - 14 March 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/aib-young-portrait-prize-2026
   Details: The annual AIB Young Portrait Prize returns in 2026. Open to young people across the island of Irela...

10. AIB Portrait Prize 2026
   Dates: 14 November 2026 - 14 March 2027
   Museum: National Gallery of Ireland
   URL: https://www.nationalgallery.ie/art-and-artists/exhibitions/upcoming-exhibitions/aib-portrait-prize-2026
   Details: The annual AIB Portrait Prize returns in 2026, once again celebrating contemporary portraiture by Ir...

Saved 10 exhibitions to exhibitions.json
```