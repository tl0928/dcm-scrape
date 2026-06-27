# DataCenterMap Scraper

Scraper for [datacentermap.com](https://www.datacentermap.com) with geography-scoped
collection, US geocoding, and FIPS enrichment.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

## Quick start

```bash
pip install -r requirements.txt

# Interactive — prompts for Country / State / City
python scripts/scrape.py

# Or pass geography as flags
python scripts/scrape.py --state Ohio
python scripts/scrape.py --state Ohio --city Cleveland
python scripts/scrape.py --country Germany

# Smoke-test with 10 records first
python scripts/scrape.py --state Ohio --sample 10
```

## Geocode (US only)

```bash
python scripts/geocode.py output/usa_ohio.jsonl \
    --output-jsonl output/usa_ohio_geocoded.jsonl \
    --output-csv   output/usa_ohio.csv
```

Adds lat/lon, FIPS codes (state, county, census tract, block), county name, and
state abbreviation via the US Census Geocoder + Nominatim/OSM.

## Output

| File | Description |
| --- | --- |
| `output/<scope>.jsonl` | Raw scrape, one record per line, resume-safe |
| `output/<scope>_geocoded.jsonl` | Enriched with `geo` block |
| `output/<scope>.csv` | Flat CSV, 16 columns |
| `output/failed_geocode.txt` | URLs that couldn't be geocoded |

See [CLAUDE.md](CLAUDE.md) for full field reference, schema, and CLI options.

## Variables collected

### scrape.py — all geographies

| Field | Description |
| --- | --- |
| `name` | Data center name |
| `operator_name` | Owning / operating company |
| `address` | Street address |
| `city` | City |
| `state` | State or region (full name) |
| `country` | Country |
| `postal` | ZIP / postal code |
| `detail_url` | Link to the datacentermap.com listing page |
| `latitude` | Latitude (from the site) |
| `longitude` | Longitude (from the site) |

### geocode.py — US only (added on top of the above)

| Field | Source | Description |
| --- | --- | --- |
| `state_abbr` | Nominatim | Two-letter state code (e.g. `OH`) |
| `county_name` | Census / Nominatim | County name (e.g. `Cuyahoga County`) |
| `display_name` | Nominatim | Full formatted address string |
| `fips_state` | Census | 2-digit state FIPS code (e.g. `39`) |
| `fips_county` | Census | 3-digit county FIPS code (e.g. `035`) |
| `census_tract` | Census | 6-digit census tract (e.g. `502100`) |
| `census_block` | Census | Block group number |

Lat/lon from the scraper are kept as-is; geocoders only fill them in when the site left them blank.

## Available geographies

Names are case-insensitive: `--country "United Kingdom"` and `--country "united kingdom"` both work.

### Countries

179 countries, sorted by number of data centers. Counts are from the site's own map UI and may be lower than what the scraper actually harvests — the scraper uses the sitemap, which includes listings the map UI filters out.

| Country | DCs |
| --- | --- |
| USA | 4,435 |
| United Kingdom | 555 |
| Germany | 524 |
| France | 394 |
| China | 369 |
| India | 296 |
| Canada | 288 |
| Australia | 284 |
| Japan | 257 |
| Italy | 255 |
| Brazil | 214 |
| Spain | 212 |
| Indonesia | 198 |
| Russia | 187 |
| The Netherlands | 186 |
| Ireland | 129 |
| Finland | 125 |
| Sweden | 117 |
| Malaysia | 115 |
| Switzerland | 114 |
| Poland | 108 |
| Norway | 107 |
| South Korea | 102 |
| Denmark | 88 |
| Hong Kong | 84 |
| Turkey | 81 |
| Israel | 67 |
| Singapore | 66 |
| Mexico | 65 |
| South Africa | 64 |
| Romania | 64 |
| Chile | 64 |
| Thailand | 62 |
| New Zealand | 62 |
| Saudi Arabia | 60 |
| United Arab Emirates | 57 |
| Czech Republic | 54 |
| Austria | 52 |
| Belgium | 47 |
| Portugal | 46 |
| Argentina | 45 |
| Philippines | 44 |
| Vietnam | 42 |
| Colombia | 39 |
| Taiwan | 37 |
| Ukraine | 36 |
| Pakistan | 31 |
| Bulgaria | 30 |
| Greece | 29 |
| Nigeria | 28 |
| Latvia | 24 |
| Lithuania | 20 |
| Slovenia | 20 |
| Kenya | 19 |
| Iran | 19 |
| Kazakhstan | 17 |
| Croatia | 17 |
| Hungary | 17 |
| Panama | 17 |
| Oman | 15 |
| Cyprus | 15 |
| Bangladesh | 15 |
| Morocco | 14 |
| Luxembourg | 14 |
| Slovakia | 14 |
| Peru | 13 |
| Egypt | 13 |
| Estonia | 12 |
| Serbia | 12 |
| Costa Rica | 12 |
| Malta | 12 |
| Tanzania | 11 |
| Iceland | 11 |
| Qatar | 11 |
| Angola | 10 |
| Cambodia | 10 |
| Mauritius | 10 |
| Uruguay | 10 |
| Sri Lanka | 9 |
| Nepal | 9 |
| Ecuador | 9 |
| Paraguay | 8 |
| Ghana | 8 |
| Puerto Rico | 8 |
| Jordan | 8 |
| Bahrain | 8 |
| Guatemala | 7 |
| Mongolia | 7 |
| Algeria | 7 |
| Senegal | 7 |
| Macedonia | 7 |
| Venezuela | 7 |
| Liechtenstein | 7 |
| Ethiopia | 6 |
| Uzbekistan | 6 |
| Moldova | 6 |
| Ivory Coast | 6 |
| Mozambique | 6 |
| Gibraltar | 6 |
| Bolivia | 6 |
| Isle of Man | 6 |
| Libya | 6 |
| Guam | 5 |
| Botswana | 5 |
| Albania | 5 |
| Tunisia | 5 |
| Trinidad and Tobago | 5 |
| Myanmar | 5 |
| Georgia | 5 |
| Reunion | 5 |
| Kuwait | 5 |
| Jersey | 5 |
| Uganda | 4 |
| Bosnia and Herzegovina | 4 |
| DR Congo | 4 |
| Armenia | 4 |
| Honduras | 4 |
| Brunei | 4 |
| Zimbabwe | 3 |
| El Salvador | 3 |
| New Caledonia | 3 |
| Dominican Republic | 3 |
| Madagascar | 3 |
| Monaco | 3 |
| Djibouti | 3 |
| Curacao | 3 |
| Rwanda | 3 |
| Zambia | 3 |
| Kyrgyzstan | 3 |
| Nicaragua | 3 |
| Azerbaijan | 3 |
| Afghanistan | 3 |
| Bahamas | 3 |
| Bhutan | 3 |
| Guernsey | 3 |
| Maldives | 3 |
| Lesotho | 3 |
| Andorra | 3 |
| Namibia | 2 |
| French Polynesia | 2 |
| Belarus | 2 |
| Togo | 2 |
| Cameroon | 2 |
| Jamaica | 2 |
| Bermuda | 2 |
| Laos | 2 |
| Lebanon | 2 |
| Sudan | 2 |
| Cayman Islands | 2 |
| Papua New Guinea | 2 |
| Suriname | 2 |
| Greenland | 2 |
| Mayotte | 1 |
| Iraq | 1 |
| Guyana | 1 |
| Syria | 1 |
| Martinique | 1 |
| Guinea | 1 |
| Burkina Faso | 1 |
| Macau | 1 |
| French Guiana | 1 |
| Mauritania | 1 |
| North Korea | 1 |
| Saint Kitts and Nevis | 1 |
| Malawi | 1 |
| Republic of the Congo | 1 |
| Gambia | 1 |
| Palestine | 1 |
| Gabon | 1 |
| Mali | 1 |
| Benin | 1 |
| Equatorial Guinea | 1 |
| Eswatini | 1 |
| Kosovo | 1 |
| Solomon Islands | 1 |
| Seychelles | 1 |
| Sierra Leone | 1 |
| Somalia | 1 |
| US Virgin Islands | 1 |

### USA — states

Use with `--state <name>` (defaults to USA). Example: `--state Virginia`

| State | DCs | Cities |
| --- | --- | --- |
| Virginia | 288 | 42 |
| Ohio | 116 | 35 |
| Texas | 114 | 40 |
| California | 71 | 23 |
| Oregon | 71 | 7 |
| Georgia | 59 | 18 |
| Illinois | 51 | 14 |
| Pennsylvania | 39 | 17 |
| New York | 33 | 14 |
| North Carolina | 32 | 13 |
| Arizona | 30 | 11 |
| Missouri | 29 | 8 |
| Maryland | 29 | 8 |
| Indiana | 29 | 6 |
| Washington | 26 | 12 |
| Florida | 21 | 10 |
| Utah | 18 | 9 |
| Mississippi | 18 | 7 |
| Minnesota | 16 | 8 |
| Tennessee | 16 | 12 |
| New Jersey | 15 | 10 |
| Michigan | 14 | 9 |
| Iowa | 10 | 4 |
| Massachusetts | 9 | 7 |
| Colorado | 9 | 5 |
| North Dakota | 9 | 7 |
| Nevada | 9 | 5 |
| Oklahoma | 8 | 3 |
| Wisconsin | 7 | 7 |
| Connecticut | 5 | 5 |
| Kentucky | 5 | 4 |
| Nebraska | 4 | 4 |
| South Carolina | 4 | 4 |
| Kansas | 4 | 4 |
| West Virginia | 4 | 4 |
| District of Columbia | 3 | 1 |
| Alaska | 3 | 2 |
| Louisiana | 3 | 2 |
| Montana | 3 | 2 |
| Wyoming | 3 | 2 |
| Alabama | 2 | 2 |
| Arkansas | 2 | 2 |
| Idaho | 1 | 1 |
| Hawaii | 1 | 1 |
| South Dakota | 1 | 1 |
| New Hampshire | 1 | 1 |
| New Mexico | 1 | 1 |
| Maine | 1 | 1 |

### USA — cities by state

Use with `--state <state> --city <city>`. Example: `--state Virginia --city Ashburn`

**Virginia:** Aldie · Appomattox · Ashburn · Blacksburg · Bristow · Carters Store · Chantilly · Charlottesville · Chester · Colonial Heights · Cornelia · Cosner's Corner · Culpeper · Duffield · Dulles · Fredericksburg · Gainesville · Haymarket · Herndon · King George · Ladysmith · Leesburg · Linton Hall · Louisa · Manassas · McLean · Mineral · Reston · Richmond · Ruther Glen · South Riding · Springfield · Stafford · Sterling · Stevensburg · Stone Ridge · Thornburg · Tysons · Vienna · Virginia Beach · Warrenton · Woodford

**Ohio:** Akron · Blue Ash · Cincinnati · Clarington · Cleveland · Columbus · Conesville · Dublin · Galena · Galloway · Hamilton · Hilliard · Johnstown · Lebanon · Lima · Lorain · Mansfield · Mantua · Marysville · Mason · Massillon · Mayfield Hts · Niles · Pataskala · Plain City · Richfield · Sandusky · Sidney · Sprigg Township · Springfield · Toledo · Warren · Westerville · Xenia · Youngstown

**Texas:** Abernathy · Abilene · Allen · Andrews · Austin · Bastrop · Baytown · Carrollton · Colorado City · Dallas · De Soto · Doole · El Paso · Elmendorf · Forest Hill · Fort Worth · Garland · Georgetown · Glen Rose · Granbury · Happy · Houston · Jarrell · Katy · Lewisville · Lufkin · Mansfield · Marion · McAllen · Midland · Odessa · Plano · Richardson · Riesel · Rockdale · San Antonio · San Marcos · Taylor · Tyler · Wink

**California:** Anaheim · Burbank · Calipatria · El Segundo · Fremont · Gilroy · Hayward · Irvine · Kearney Mesa · Los Angeles · Modesto · Monterey Park · Newark · Oakland · Pittsburg · Redwood City · Romoland · San Diego · San Francisco · San Jose · Santa Clara · Sunnyvale · Vernon

**Oregon:** Beaverton · Boardman · Hermiston · Hillsboro · La Pine · Prineville · Umatilla

**Georgia:** Alpharetta · Appling · Atlanta · Austell · Barnesville · Brookhaven · Carrollton · Dalton · Douglasville · Dry Branch · Lithia Springs · Macon · Maysville · Norcross · Sandersville · Vidalia · Villa Rica · Washington

**Illinois:** Aurora · Bloomington · Chicago · Elk Grove Village · Franklin Park · Lisle · Lombard · Mt Prospect · Naperville · Northlake · Oak Brook · Peoria · Rosemont · Volo

**Pennsylvania:** Allentown · Berwick · Eynon · Freeport · Kennerdell · King of Prussia · Lancaster · MacArthur · Malvern · McAdoo · McKees Rocks · Nesquehoning · Philadelphia · Pittsburgh · Sharon · Springdale · Wampum

**New York:** Albany · Albion · Brooklyn · Buffalo · Commack · Manhattan · New York · Niagara Falls · Orangeburg · Pearl River · Rochester · Totowa · Westbury · Williamsville

**North Carolina:** Charlotte · Durham · Fayetteville · Hamlet · Lenoir · Madison · Maiden · Morrisville · Newton · Raleigh · Rosman · Sylva · Winston-Salem

**Arizona:** Buckeye · Chandler · Laveen · Mesa · Peoria · Phoenix · Scottsdale · Tempe · Tucson · Waddell · Wintersburg

**Missouri:** Columbia · Jefferson City · Kansas City · Mexico · New Florence · Rolla · Springfield · St. Louis

**Maryland:** Baltimore · Frederick · Glen Burnie · Laurel · Lusby · Owings Mills · Severn · Silver Spring

**Indiana:** Charlestown · Hobart · Indianapolis · New Carlisle · Portage · South Bend

**Washington:** Bellevue · Bothell · Burbank · East Wenatchee · Issaquah · Moses Lake · Puyallup · Richland · Seattle · Tukwila · Walla Walla · Wenatchee

**Florida:** Boca Raton · Fort Meade · Jacksonville · Jacksonville Beach · Miami · Orlando · Pompano Beach · Seminole · Tampa · Winter Haven

**Utah:** Cedar City · Delta · Lindon · Midvale · Nephi · Orem · Provo · West Jordan · West Valley City

**Mississippi:** Brandon · Canton · Clinton · Meridian · Ridgeland · Vicksburg · Wiggins

**Minnesota:** Becker · Blue Earth · Eagan · Eden Prairie · Faribault · Minneapolis · New Brighton · Randolph Township

**Tennessee:** Chattanooga · Crossville · Jackson · Jellico · Knoxville · Lenoir City · Memphis · Mountain City · Nashville · New Tazewell · Whitehaven · Winfield

**New Jersey:** Branchburg · Bridgewater Township · Carlstadt · Cedar Knolls · Clifton · Newark · Nutley · Piscataway · Secaucus · Weehawken

**Michigan:** Alpena · Ann Arbor · Battle Creek · Byron Center · Grand Rapids · Lansing · Monroe · Southfield · Troy

**Iowa:** Adair · Des Moines · Sioux City · Waukee

**Massachusetts:** Bedford · Boston · Cambridge · Chelmsford · Marlborough · Needham · Somerville

**Colorado:** Broomfield · Centennial · Denver · Englewood · Walsenburg

**North Dakota:** Bismarck · Ellendale · Fargo · Harwood · Jamestown · Nekoma · Williston

**Nevada:** Fallon · Las Vegas · Reno · Sparks · Wells

**Oklahoma:** Broken Arrow · Oklahoma City · Tulsa

**Wisconsin:** Beaver Dam · Harrison · Madison · Marshfield · Menomonie · Milwaukee · West Milwaukee

**Connecticut:** Bloomfield · Shelton · Stamford · Trumbull · Wallingford

**Kentucky:** Florence · Lexington · Louisville · Russell

**Nebraska:** Aurora · Hayland · Lincoln · Omaha

**South Carolina:** Blythewood · Camden · Gaffney · Spartanburg

**Kansas:** Kansas City · Lenexa · Olathe · Osawatomie

**West Virginia:** Bridgeport · Charleston · South Charleston · Star City

**District of Columbia:** Washington D.C.

**Alaska:** Anchorage · Palmer

**Louisiana:** Baton Rouge · Boyce

**Montana:** Billings · Butte

**Wyoming:** Cheyenne · Sheridan

**Alabama:** Auburn · Mobile

**Arkansas:** Russellville · Wrightsville

**Idaho:** Weiser

**Hawaii:** Kapolei

**South Dakota:** Toronto

**New Hampshire:** Bedford

**New Mexico:** Albuquerque

**Maine:** Portland
