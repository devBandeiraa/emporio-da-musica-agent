"""Accent-insensitive, typo-tolerant search over the product catalog."""

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from emporio_agent.models import Category, Product
from emporio_agent.store import Store
from emporio_agent.text import compact, normalize

FUZZY_CUTOFF = 82
MIN_FUZZY_LENGTH = 4
MIN_MODEL_LENGTH = 3
MAX_SIMILAR = 3

_STOPWORDS_TEXT = (
    "a as com da das de do dos e em ha me na nas no nos o os para pra por que quero tem um uma "
    "uns umas voces"
)
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())

# The store does not sell these (§7.1). A guitar's "pré-amplificador" must not turn a search
# for "amplificador" into a match.
_ACCESSORIES_TEXT = (
    "amplificador amplificadores cabo cabos case cases palheta palhetas pedal pedais"
)
ACCESSORY_WORDS = frozenset(_ACCESSORIES_TEXT.split())

# The words customers use for each category. Categories without products are listed too,
# so "saxofone" can be answered with "not in the catalog" instead of an unrelated match.
CATEGORY_ALIASES = {
    1: "guitarra guitarras",
    2: "baixo baixos contrabaixo contrabaixos",
    3: "bateria baterias percussao",
    4: "teclado teclados piano pianos sintetizador sintetizadores",
    5: "violao violoes",
    6: "flauta flautas clarinete clarinetes saxofone saxofones sax oboe oboes",
    7: "trompete trompetes trombone trombones tuba tubas trompa trompas",
    8: "violino violinos viola violas violoncelo violoncelos",
    9: "ukulele ukuleles uke",
}

# Specs mix English and Portuguese ("steel", "Preto"); customers search in Portuguese.
SPEC_TRANSLATIONS = {
    "steel": "aco",
    "yes": "eletrico eletroacustico",
    "black": "preto",
    "red": "vermelho",
    "blue": "azul",
    "mahogany": "mogno",
}


@dataclass(frozen=True)
class SearchResult:
    """`matches` satisfy the whole query; `similar` only part of it."""

    matches: list[Product]
    similar: list[Product]


def find_category(store: Store, text: str) -> Category | None:
    """Resolve free text ("violões", "Sopro") to a category, by alias or by name."""
    wanted = normalize(text)
    for category_id, aliases in CATEGORY_ALIASES.items():
        if wanted in aliases.split():
            return store.categories[category_id]
    for category in store.categories.values():
        if wanted and wanted in normalize(category.name):
            return category
    return None


def empty_category_in(store: Store, query: str) -> Category | None:
    """Return a category without products mentioned in the query, e.g. "saxofone alto"."""
    stocked = {product.category_id for product in store.products.values()}
    for token in normalize(query).split():
        category = find_category(store, token)
        if category and category.category_id not in stocked:
            return category
    return None


def _spec_tokens(product: Product) -> set[str]:
    tokens: set[str] = set()
    for key, value in product.specs.items():
        tokens.update(normalize(value).split())
        tokens.update(SPEC_TRANSLATIONS.get(normalize(value), "").split())
        # "strings" holds a count for guitars and basses, a material for the others.
        if key == "strings" and value.isdigit():
            tokens.add("cordas")
    tokens.discard("no")
    return tokens


def _structured_tokens(store: Store, product: Product) -> set[str]:
    tokens = set(normalize(product.name).split())
    tokens.update(normalize(store.categories[product.category_id].name).split())
    tokens.update(CATEGORY_ALIASES[product.category_id].split())
    tokens.update(_spec_tokens(product))
    return tokens


def _description_tokens(product: Product) -> set[str]:
    return set(normalize(product.description or "").split()) - ACCESSORY_WORDS


def _token_matches(token: str, structured: set[str], description: set[str]) -> bool:
    # Descriptions need an exact hit: fuzzy matching there would turn "amplificador",
    # which the store does not sell, into any product "amplificado".
    if token in structured or token in description:
        return True
    if any(ch.isdigit() for ch in token) and len(token) > 1:
        return any(token in candidate for candidate in structured)
    if len(token) < MIN_FUZZY_LENGTH:
        return False
    best = process.extractOne(token, structured, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF)
    return best is not None


def _query_tokens(query: str) -> list[str]:
    return [token for token in normalize(query).split() if token not in STOPWORDS]


def search_products(store: Store, query: str) -> SearchResult:
    """Find products by brand, model, category or characteristic."""
    tokens = _query_tokens(query)
    if not tokens:
        return SearchResult(matches=[], similar=[])

    wanted_model = compact(" ".join(tokens))
    full_name: list[Product] = []
    every_token: list[Product] = []
    partial: list[tuple[float, Product]] = []

    for product in store.products.values():
        if len(wanted_model) >= MIN_MODEL_LENGTH and wanted_model in compact(product.name):
            full_name.append(product)
            continue
        structured = _structured_tokens(store, product)
        description = _description_tokens(product)
        hits = sum(_token_matches(token, structured, description) for token in tokens)
        if hits == len(tokens):
            every_token.append(product)
        elif hits:
            partial.append((hits / len(tokens), product))

    partial.sort(key=lambda scored: -scored[0])
    return SearchResult(
        matches=full_name + every_token,
        similar=[product for _, product in partial[:MAX_SIMILAR]],
    )
