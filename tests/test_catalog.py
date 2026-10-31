import pytest

from emporio_agent.catalog import find_category, search_products


def ids(products):
    return {product.product_id for product in products}


@pytest.mark.parametrize(
    "query",
    ["Takamine GD20", "takamine gd-20", "TAKAMINE GD 20", "takamne gd20", "gd20"],
)
def test_finds_a_model_with_spelling_variations(store, query):
    assert 95 in ids(search_products(store, query).matches)


def test_ignores_accents(store):
    assert ids(search_products(store, "violão yamaha f310").matches) == {87}


def test_a_model_prefix_returns_both_variants(store):
    assert {93, 108} <= ids(search_products(store, "Martin D-28").matches)


def test_searches_by_category_word(store):
    assert ids(search_products(store, "contrabaixo").matches) == {135, 136, 137, 138}


def test_searches_by_characteristic(store):
    matches = ids(search_products(store, "violão 7 cordas nylon").matches)
    assert matches == {109, 110, 111, 113}


def test_translates_spec_values(store):
    assert 87 in ids(search_products(store, "violão aço").matches)
    assert 94 in ids(search_products(store, "violão eletroacústico").matches)


def test_string_count_is_searchable_on_basses(store):
    assert ids(search_products(store, "baixo 4 cordas").matches) == {135, 136, 137, 138}


def test_contradicted_description_does_not_create_a_match(store):
    # Descriptions of 135-144 mention these models, but the store does not sell them.
    for query in ["Fender Jazz Bass", "Pearl Export", "baixo 5 cordas"]:
        assert search_products(store, query).matches == []


def test_unknown_model_offers_similar_products(store):
    result = search_products(store, "Takamine GD99")
    assert result.matches == []
    assert result.similar
    assert all("Takamine" in product.name for product in result.similar)


@pytest.mark.parametrize("query", ["cabo P10", "palheta", "pedal", "amplificador"])
def test_accessories_are_not_found(store, query):
    assert search_products(store, query).matches == []


@pytest.mark.parametrize("query", ["", "   ", "de para com", "?!"])
def test_blank_queries_return_nothing(store, query):
    result = search_products(store, query)
    assert result.matches == []
    assert result.similar == []


@pytest.mark.parametrize(
    ("text", "category_id"),
    [
        ("violões", 5),
        ("VIOLAO", 5),
        ("contrabaixo", 2),
        ("piano", 4),
        ("saxofone", 6),
        ("trompete", 7),
        ("violino", 8),
        ("Baterias e Percussão", 3),
        ("Madeiras", 6),
    ],
)
def test_find_category(store, text, category_id):
    assert find_category(store, text).category_id == category_id


@pytest.mark.parametrize("text", ["", "cabo", "gaita"])
def test_find_category_returns_none_when_unknown(store, text):
    assert find_category(store, text) is None
