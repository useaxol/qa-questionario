"""Base de aeroportos (IATA) usada para busca, exibição e cálculo de distância.

A lista cobre os principais aeroportos de todos os continentes. Aeroportos
desconhecidos continuam funcionando no monitor: apenas não têm coordenada,
e a estimativa de distância cai para um valor padrão.
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    city: str
    country: str
    lat: float
    lon: float

    @property
    def label(self) -> str:
        return f"{self.iata} - {self.city}, {self.country}"


# iata, nome, cidade, país, lat, lon
_RAW: Tuple[Tuple[str, str, str, str, float, float], ...] = (
    # Brasil
    ("GRU", "Guarulhos", "São Paulo", "Brasil", -23.43, -46.47),
    ("CGH", "Congonhas", "São Paulo", "Brasil", -23.63, -46.66),
    ("VCP", "Viracopos", "Campinas", "Brasil", -23.01, -47.13),
    ("GIG", "Galeão", "Rio de Janeiro", "Brasil", -22.81, -43.25),
    ("SDU", "Santos Dumont", "Rio de Janeiro", "Brasil", -22.91, -43.16),
    ("BSB", "Juscelino Kubitschek", "Brasília", "Brasil", -15.87, -47.92),
    ("CNF", "Confins", "Belo Horizonte", "Brasil", -19.63, -43.97),
    ("POA", "Salgado Filho", "Porto Alegre", "Brasil", -29.99, -51.17),
    ("CWB", "Afonso Pena", "Curitiba", "Brasil", -25.53, -49.18),
    ("FLN", "Hercílio Luz", "Florianópolis", "Brasil", -27.67, -48.55),
    ("SSA", "Deputado Luís Eduardo Magalhães", "Salvador", "Brasil", -12.91, -38.33),
    ("REC", "Guararapes", "Recife", "Brasil", -8.13, -34.92),
    ("FOR", "Pinto Martins", "Fortaleza", "Brasil", -3.78, -38.53),
    ("NAT", "São Gonçalo do Amarante", "Natal", "Brasil", -5.77, -35.37),
    ("MCZ", "Zumbi dos Palmares", "Maceió", "Brasil", -9.51, -35.79),
    ("JPA", "Castro Pinto", "João Pessoa", "Brasil", -7.15, -34.95),
    ("AJU", "Santa Maria", "Aracaju", "Brasil", -10.98, -37.07),
    ("BEL", "Val de Cans", "Belém", "Brasil", -1.38, -48.48),
    ("MAO", "Eduardo Gomes", "Manaus", "Brasil", -3.04, -60.05),
    ("SLZ", "Marechal Cunha Machado", "São Luís", "Brasil", -2.59, -44.23),
    ("IGU", "Cataratas", "Foz do Iguaçu", "Brasil", -25.60, -54.49),
    ("VIX", "Eurico de Aguiar Salles", "Vitória", "Brasil", -20.26, -40.29),
    ("GYN", "Santa Genoveva", "Goiânia", "Brasil", -16.63, -49.22),
    ("CGB", "Marechal Rondon", "Cuiabá", "Brasil", -15.65, -56.12),
    ("CGR", "Campo Grande", "Campo Grande", "Brasil", -20.47, -54.67),
    ("PMW", "Palmas", "Palmas", "Brasil", -10.29, -48.36),
    ("BPS", "Porto Seguro", "Porto Seguro", "Brasil", -16.44, -39.08),
    ("IOS", "Ilhéus", "Ilhéus", "Brasil", -14.82, -39.03),
    ("FEN", "Fernando de Noronha", "Fernando de Noronha", "Brasil", -3.85, -32.42),
    # América do Sul
    ("EZE", "Ezeiza", "Buenos Aires", "Argentina", -34.82, -58.54),
    ("AEP", "Aeroparque", "Buenos Aires", "Argentina", -34.56, -58.42),
    ("COR", "Pajas Blancas", "Córdoba", "Argentina", -31.31, -64.21),
    ("MDZ", "El Plumerillo", "Mendoza", "Argentina", -32.83, -68.79),
    ("BRC", "Bariloche", "Bariloche", "Argentina", -41.15, -71.16),
    ("USH", "Ushuaia", "Ushuaia", "Argentina", -54.84, -68.30),
    ("SCL", "Arturo Merino Benítez", "Santiago", "Chile", -33.39, -70.79),
    ("MVD", "Carrasco", "Montevidéu", "Uruguai", -34.84, -56.03),
    ("ASU", "Silvio Pettirossi", "Assunção", "Paraguai", -25.24, -57.52),
    ("LIM", "Jorge Chávez", "Lima", "Peru", -12.02, -77.11),
    ("CUZ", "Velasco Astete", "Cusco", "Peru", -13.54, -71.94),
    ("BOG", "El Dorado", "Bogotá", "Colômbia", 4.70, -74.15),
    ("MDE", "José María Córdova", "Medellín", "Colômbia", 6.16, -75.42),
    ("CTG", "Rafael Núñez", "Cartagena", "Colômbia", 10.44, -75.51),
    ("UIO", "Mariscal Sucre", "Quito", "Equador", -0.13, -78.36),
    ("GYE", "José Joaquín de Olmedo", "Guayaquil", "Equador", -2.16, -79.88),
    ("VVI", "Viru Viru", "Santa Cruz", "Bolívia", -17.64, -63.14),
    ("CCS", "Simón Bolívar", "Caracas", "Venezuela", 10.60, -66.99),
    # América Central e Caribe
    ("PTY", "Tocumen", "Cidade do Panamá", "Panamá", 9.07, -79.38),
    ("SJO", "Juan Santamaría", "San José", "Costa Rica", 9.99, -84.21),
    ("HAV", "José Martí", "Havana", "Cuba", 22.99, -82.41),
    ("PUJ", "Punta Cana", "Punta Cana", "Rep. Dominicana", 18.57, -68.36),
    ("SJU", "Luis Muñoz Marín", "San Juan", "Porto Rico", 18.44, -66.00),
    ("AUA", "Reina Beatrix", "Oranjestad", "Aruba", 12.50, -70.02),
    ("CUR", "Hato", "Willemstad", "Curaçao", 12.19, -68.96),
    ("MBJ", "Sangster", "Montego Bay", "Jamaica", 18.50, -77.91),
    # América do Norte
    ("MEX", "Benito Juárez", "Cidade do México", "México", 19.44, -99.07),
    ("CUN", "Cancún", "Cancún", "México", 21.04, -86.87),
    ("GDL", "Miguel Hidalgo", "Guadalajara", "México", 20.52, -103.31),
    ("MTY", "Mariano Escobedo", "Monterrey", "México", 25.78, -100.11),
    ("JFK", "John F. Kennedy", "Nova York", "EUA", 40.64, -73.78),
    ("EWR", "Newark", "Nova York", "EUA", 40.69, -74.17),
    ("LGA", "LaGuardia", "Nova York", "EUA", 40.78, -73.87),
    ("MIA", "Miami", "Miami", "EUA", 25.79, -80.29),
    ("FLL", "Fort Lauderdale", "Fort Lauderdale", "EUA", 26.07, -80.15),
    ("MCO", "Orlando", "Orlando", "EUA", 28.43, -81.31),
    ("TPA", "Tampa", "Tampa", "EUA", 27.98, -82.53),
    ("LAX", "Los Angeles", "Los Angeles", "EUA", 33.94, -118.41),
    ("SFO", "San Francisco", "San Francisco", "EUA", 37.62, -122.38),
    ("SEA", "Tacoma", "Seattle", "EUA", 47.45, -122.31),
    ("ORD", "O'Hare", "Chicago", "EUA", 41.98, -87.90),
    ("ATL", "Hartsfield-Jackson", "Atlanta", "EUA", 33.64, -84.43),
    ("DFW", "Dallas/Fort Worth", "Dallas", "EUA", 32.90, -97.04),
    ("IAH", "George Bush", "Houston", "EUA", 29.98, -95.34),
    ("BOS", "Logan", "Boston", "EUA", 42.36, -71.01),
    ("IAD", "Dulles", "Washington", "EUA", 38.95, -77.46),
    ("DEN", "Denver", "Denver", "EUA", 39.86, -104.67),
    ("LAS", "Harry Reid", "Las Vegas", "EUA", 36.08, -115.15),
    ("PHX", "Sky Harbor", "Phoenix", "EUA", 33.43, -112.01),
    ("SAN", "San Diego", "San Diego", "EUA", 32.73, -117.19),
    ("HNL", "Daniel K. Inouye", "Honolulu", "EUA", 21.32, -157.92),
    ("YYZ", "Pearson", "Toronto", "Canadá", 43.68, -79.63),
    ("YVR", "Vancouver", "Vancouver", "Canadá", 49.19, -123.18),
    ("YUL", "Trudeau", "Montreal", "Canadá", 45.47, -73.74),
    ("YYC", "Calgary", "Calgary", "Canadá", 51.11, -114.02),
    # Europa
    ("LHR", "Heathrow", "Londres", "Reino Unido", 51.47, -0.45),
    ("LGW", "Gatwick", "Londres", "Reino Unido", 51.15, -0.18),
    ("STN", "Stansted", "Londres", "Reino Unido", 51.88, 0.24),
    ("MAN", "Manchester", "Manchester", "Reino Unido", 53.36, -2.27),
    ("EDI", "Edimburgo", "Edimburgo", "Reino Unido", 55.95, -3.37),
    ("DUB", "Dublin", "Dublin", "Irlanda", 53.43, -6.27),
    ("CDG", "Charles de Gaulle", "Paris", "França", 49.01, 2.55),
    ("ORY", "Orly", "Paris", "França", 48.73, 2.37),
    ("NCE", "Côte d'Azur", "Nice", "França", 43.66, 7.22),
    ("LYS", "Saint-Exupéry", "Lyon", "França", 45.73, 5.08),
    ("MRS", "Provence", "Marselha", "França", 43.44, 5.22),
    ("AMS", "Schiphol", "Amsterdã", "Holanda", 52.31, 4.76),
    ("BRU", "Zaventem", "Bruxelas", "Bélgica", 50.90, 4.48),
    ("FRA", "Frankfurt", "Frankfurt", "Alemanha", 50.04, 8.56),
    ("MUC", "Franz Josef Strauss", "Munique", "Alemanha", 48.35, 11.79),
    ("BER", "Brandenburg", "Berlim", "Alemanha", 52.37, 13.50),
    ("DUS", "Düsseldorf", "Düsseldorf", "Alemanha", 51.28, 6.77),
    ("HAM", "Hamburgo", "Hamburgo", "Alemanha", 53.63, 9.99),
    ("ZRH", "Zurique", "Zurique", "Suíça", 47.46, 8.55),
    ("GVA", "Genebra", "Genebra", "Suíça", 46.24, 6.11),
    ("VIE", "Schwechat", "Viena", "Áustria", 48.11, 16.57),
    ("CPH", "Kastrup", "Copenhague", "Dinamarca", 55.62, 12.65),
    ("ARN", "Arlanda", "Estocolmo", "Suécia", 59.65, 17.92),
    ("OSL", "Gardermoen", "Oslo", "Noruega", 60.19, 11.10),
    ("HEL", "Vantaa", "Helsinque", "Finlândia", 60.32, 24.96),
    ("KEF", "Keflavík", "Reykjavík", "Islândia", 63.99, -22.61),
    ("MAD", "Barajas", "Madri", "Espanha", 40.49, -3.57),
    ("BCN", "El Prat", "Barcelona", "Espanha", 41.30, 2.08),
    ("AGP", "Málaga", "Málaga", "Espanha", 36.68, -4.50),
    ("PMI", "Palma de Maiorca", "Palma", "Espanha", 39.55, 2.74),
    ("LPA", "Gran Canaria", "Las Palmas", "Espanha", 27.93, -15.39),
    ("LIS", "Humberto Delgado", "Lisboa", "Portugal", 38.77, -9.13),
    ("OPO", "Francisco Sá Carneiro", "Porto", "Portugal", 41.24, -8.68),
    ("FAO", "Faro", "Faro", "Portugal", 37.01, -7.97),
    ("FNC", "Madeira", "Funchal", "Portugal", 32.69, -16.78),
    ("FCO", "Fiumicino", "Roma", "Itália", 41.80, 12.25),
    ("MXP", "Malpensa", "Milão", "Itália", 45.63, 8.72),
    ("VCE", "Marco Polo", "Veneza", "Itália", 45.51, 12.35),
    ("NAP", "Capodichino", "Nápoles", "Itália", 40.88, 14.29),
    ("ATH", "Eleftherios Venizelos", "Atenas", "Grécia", 37.94, 23.95),
    ("JTR", "Santorini", "Santorini", "Grécia", 36.40, 25.48),
    ("IST", "Istambul", "Istambul", "Turquia", 41.26, 28.74),
    ("SAW", "Sabiha Gökçen", "Istambul", "Turquia", 40.90, 29.31),
    ("PRG", "Václav Havel", "Praga", "Tchéquia", 50.10, 14.26),
    ("WAW", "Chopin", "Varsóvia", "Polônia", 52.17, 20.97),
    ("BUD", "Ferenc Liszt", "Budapeste", "Hungria", 47.44, 19.26),
    ("OTP", "Henri Coandă", "Bucareste", "Romênia", 44.57, 26.10),
    ("SOF", "Sofia", "Sofia", "Bulgária", 42.70, 23.41),
    ("ZAG", "Franjo Tuđman", "Zagreb", "Croácia", 45.74, 16.07),
    ("DBV", "Dubrovnik", "Dubrovnik", "Croácia", 42.56, 18.27),
    ("BEG", "Nikola Tesla", "Belgrado", "Sérvia", 44.82, 20.29),
    ("RIX", "Riga", "Riga", "Letônia", 56.92, 23.97),
    ("TLL", "Lennart Meri", "Tallinn", "Estônia", 59.41, 24.83),
    ("VNO", "Vilnius", "Vilnius", "Lituânia", 54.64, 25.29),
    ("MLA", "Malta", "Valeta", "Malta", 35.86, 14.48),
    ("SVO", "Sheremetyevo", "Moscou", "Rússia", 55.97, 37.41),
    ("LED", "Pulkovo", "São Petersburgo", "Rússia", 59.80, 30.26),
    ("TBS", "Tbilisi", "Tbilisi", "Geórgia", 41.67, 44.95),
    # Oriente Médio
    ("DXB", "Dubai", "Dubai", "Emirados Árabes", 25.25, 55.36),
    ("AUH", "Zayed", "Abu Dhabi", "Emirados Árabes", 24.43, 54.65),
    ("DOH", "Hamad", "Doha", "Catar", 25.27, 51.61),
    ("RUH", "King Khalid", "Riad", "Arábia Saudita", 24.96, 46.70),
    ("JED", "King Abdulaziz", "Jidá", "Arábia Saudita", 21.68, 39.16),
    ("TLV", "Ben Gurion", "Tel Aviv", "Israel", 32.01, 34.89),
    ("AMM", "Queen Alia", "Amã", "Jordânia", 31.72, 35.99),
    ("MCT", "Mascate", "Mascate", "Omã", 23.59, 58.28),
    ("KWI", "Kuwait", "Cidade do Kuwait", "Kuwait", 29.23, 47.97),
    # África
    ("CAI", "Cairo", "Cairo", "Egito", 30.11, 31.41),
    ("HRG", "Hurghada", "Hurghada", "Egito", 27.18, 33.80),
    ("CMN", "Mohammed V", "Casablanca", "Marrocos", 33.37, -7.59),
    ("RAK", "Menara", "Marrakech", "Marrocos", 31.61, -8.04),
    ("TUN", "Cartago", "Túnis", "Tunísia", 36.85, 10.23),
    ("JNB", "O. R. Tambo", "Joanesburgo", "África do Sul", -26.13, 28.24),
    ("CPT", "Cidade do Cabo", "Cidade do Cabo", "África do Sul", -33.97, 18.60),
    ("NBO", "Jomo Kenyatta", "Nairóbi", "Quênia", -1.32, 36.93),
    ("ADD", "Bole", "Adis Abeba", "Etiópia", 8.98, 38.80),
    ("LOS", "Murtala Muhammed", "Lagos", "Nigéria", 6.58, 3.32),
    ("ACC", "Kotoka", "Acra", "Gana", 5.61, -0.17),
    ("DKR", "Blaise Diagne", "Dacar", "Senegal", 14.67, -17.07),
    ("MRU", "Plaisance", "Port Louis", "Maurício", -20.43, 57.68),
    ("SEZ", "Seychelles", "Mahé", "Seicheles", -4.67, 55.52),
    ("ZNZ", "Zanzibar", "Zanzibar", "Tanzânia", -6.22, 39.22),
    ("LAD", "Quatro de Fevereiro", "Luanda", "Angola", -8.86, 13.23),
    ("SID", "Amílcar Cabral", "Sal", "Cabo Verde", 16.74, -22.95),
    # Ásia
    ("NRT", "Narita", "Tóquio", "Japão", 35.77, 140.39),
    ("HND", "Haneda", "Tóquio", "Japão", 35.55, 139.78),
    ("KIX", "Kansai", "Osaka", "Japão", 34.43, 135.24),
    ("ICN", "Incheon", "Seul", "Coreia do Sul", 37.46, 126.44),
    ("PEK", "Capital", "Pequim", "China", 40.08, 116.58),
    ("PVG", "Pudong", "Xangai", "China", 31.14, 121.81),
    ("CAN", "Baiyun", "Guangzhou", "China", 23.39, 113.31),
    ("HKG", "Hong Kong", "Hong Kong", "China", 22.31, 113.91),
    ("TPE", "Taoyuan", "Taipé", "Taiwan", 25.08, 121.23),
    ("SIN", "Changi", "Singapura", "Singapura", 1.36, 103.99),
    ("BKK", "Suvarnabhumi", "Bangkok", "Tailândia", 13.69, 100.75),
    ("HKT", "Phuket", "Phuket", "Tailândia", 8.11, 98.31),
    ("KUL", "Kuala Lumpur", "Kuala Lumpur", "Malásia", 2.75, 101.71),
    ("CGK", "Soekarno-Hatta", "Jacarta", "Indonésia", -6.13, 106.66),
    ("DPS", "Ngurah Rai", "Bali", "Indonésia", -8.75, 115.17),
    ("MNL", "Ninoy Aquino", "Manila", "Filipinas", 14.51, 121.02),
    ("HAN", "Noi Bai", "Hanói", "Vietnã", 21.22, 105.81),
    ("SGN", "Tan Son Nhat", "Ho Chi Minh", "Vietnã", 10.82, 106.66),
    ("REP", "Siem Reap", "Siem Reap", "Camboja", 13.41, 103.81),
    ("DEL", "Indira Gandhi", "Nova Délhi", "Índia", 28.56, 77.10),
    ("BOM", "Chhatrapati Shivaji", "Mumbai", "Índia", 19.09, 72.87),
    ("BLR", "Kempegowda", "Bengaluru", "Índia", 13.20, 77.71),
    ("MAA", "Chennai", "Chennai", "Índia", 12.99, 80.17),
    ("CCU", "Bose", "Calcutá", "Índia", 22.65, 88.45),
    ("CMB", "Bandaranaike", "Colombo", "Sri Lanka", 7.18, 79.88),
    ("MLE", "Velana", "Malé", "Maldivas", 4.19, 73.53),
    ("KTM", "Tribhuvan", "Katmandu", "Nepal", 27.70, 85.36),
    ("ALA", "Almaty", "Almaty", "Cazaquistão", 43.35, 77.04),
    # Oceania
    ("SYD", "Kingsford Smith", "Sydney", "Austrália", -33.95, 151.18),
    ("MEL", "Tullamarine", "Melbourne", "Austrália", -37.67, 144.84),
    ("BNE", "Brisbane", "Brisbane", "Austrália", -27.38, 153.12),
    ("PER", "Perth", "Perth", "Austrália", -31.94, 115.97),
    ("ADL", "Adelaide", "Adelaide", "Austrália", -34.95, 138.53),
    ("CNS", "Cairns", "Cairns", "Austrália", -16.89, 145.75),
    ("AKL", "Auckland", "Auckland", "Nova Zelândia", -37.01, 174.79),
    ("CHC", "Christchurch", "Christchurch", "Nova Zelândia", -43.49, 172.53),
    ("ZQN", "Queenstown", "Queenstown", "Nova Zelândia", -45.02, 168.74),
    ("NAN", "Nadi", "Nadi", "Fiji", -17.76, 177.44),
    ("PPT", "Faa'a", "Papeete", "Polinésia Francesa", -17.56, -149.61),
)

AIRPORTS: Dict[str, Airport] = {
    row[0]: Airport(iata=row[0], name=row[1], city=row[2], country=row[3], lat=row[4], lon=row[5])
    for row in _RAW
}

EARTH_RADIUS_KM = 6371.0
# Usado quando um dos aeroportos não está na base local.
FALLBACK_DISTANCE_KM = 3500.0


def get(iata: Optional[str]) -> Optional[Airport]:
    if not iata:
        return None
    return AIRPORTS.get(iata.strip().upper())


def label(iata: str) -> str:
    ap = get(iata)
    return ap.label if ap else (iata or "").upper()


def city_of(iata: str) -> str:
    ap = get(iata)
    return ap.city if ap else (iata or "").upper()


def all_airports() -> List[Airport]:
    return sorted(AIRPORTS.values(), key=lambda a: (a.country, a.city, a.iata))


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def search(query: str, limit: int = 20) -> List[Airport]:
    """Busca simples por código, cidade, país ou nome (sem acentuação)."""
    q = _normalize(query).strip()
    if not q:
        return all_airports()[:limit]

    scored: List[Tuple[int, Airport]] = []
    for ap in AIRPORTS.values():
        code = ap.iata.lower()
        city = _normalize(ap.city)
        country = _normalize(ap.country)
        name = _normalize(ap.name)
        if code == q:
            score = 0
        elif city.startswith(q):
            score = 1
        elif code.startswith(q):
            score = 2
        elif q in city:
            score = 3
        elif q in country or q in name:
            score = 4
        else:
            continue
        scored.append((score, ap))

    scored.sort(key=lambda item: (item[0], item[1].city))
    return [ap for _, ap in scored[:limit]]


def haversine_km(a: Airport, b: Airport) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def distance_km(origin: str, destination: str) -> float:
    a, b = get(origin), get(destination)
    if a is None or b is None:
        return FALLBACK_DISTANCE_KM
    return haversine_km(a, b)
