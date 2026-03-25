from __future__ import annotations

from datetime import datetime


PRICE_FORMATS = [
    {"name": "ГПЛ_02_001", "code": "ГПЛ_02_001", "branch": "Астана"},
    {"name": "ИПЛ_01_002", "code": "ИПЛ_01_002", "branch": "Алматы"},
]

GENERATED_PRICE_LISTS = [
    {
        "date": "21.03.2026 11:00",
        "number": "ГПЛ_02_001",
        "format": "ГПЛ_02_001",
        "activationDate": "22.03.2026",
        "user": "ФИО",
        "status": "Активен",
        "branch": "Астана",
    },
    {
        "date": "21.03.2026 11:01",
        "number": "ИПЛ_01_002",
        "format": "ИПЛ_01_002",
        "activationDate": "22.03.2026",
        "user": "ФИО",
        "status": "Активен",
        "branch": "Алматы",
    },
]

COMPETITORS_AVAILABLE = [
    {
        "id": 1,
        "supplier": "Эмити",
        "priceDate": "21.03.2026",
        "name": "Персентиль 10",
        "region": "08",
        "coefficient": 1.0,
    },
    {
        "id": 2,
        "supplier": "Эмити",
        "priceDate": "21.03.2026",
        "name": "Персентиль 20",
        "region": "08",
        "coefficient": 1.0,
    },
]

COMPETITORS_ASSIGNED_BY_FORMAT: dict[str, list[int]] = {
    "ГПЛ_02_001": [1, 2],
    "ИПЛ_01_002": [1],
}

LISTS_BY_FORMAT = {
    "ГПЛ_02_001": [
        {
            "id": 1,
            "name": "Прямые контракты",
            "code": "УЛ-0001",
            "status": "Активный",
            "type": "Фикс цена",
            "startDate": "01.03.2026",
            "endDate": "31.03.2026",
        },
        {
            "id": 2,
            "name": "Ограничения сверху",
            "code": "УЛ-0002",
            "status": "Не активный",
            "type": "Макс наценка",
            "startDate": "01.01.2026",
            "endDate": "01.01.2027",
        },
        {
            "id": 3,
            "name": "Минимальные цены",
            "code": "УЛ-0003",
            "status": "Активный",
            "type": "Фикс цены",
            "startDate": "01.03.2026",
            "endDate": "31.03.2026",
        },
        {
            "id": 4,
            "name": "Гос Цены",
            "code": "УЛ-0004",
            "status": "Активный",
            "type": "фикс цены",
            "startDate": "01.03.2026",
            "endDate": "31.03.2026",
        },
    ],
    "ИПЛ_01_002": [],
}

COUNTERPARTIES_BY_FORMAT = {
    "ГПЛ_02_001": [
        {"code": "C-001", "holding": "АСС", "name": "ТОО Аптека 1", "inn": ""},
        {"code": "C-002", "holding": "АСС", "name": "ТОО Аптека 2", "inn": ""},
        {"code": "C-003", "holding": "АСС", "name": "ТОО Аптека 3", "inn": ""},
        {"code": "C-004", "holding": "Зерде", "name": "ТОО Аптека 4", "inn": ""},
        {"code": "C-005", "holding": "Зерде", "name": "ТОО Аптека 5", "inn": ""},
    ],
    "ИПЛ_01_002": [],
}

PRICING_SETTINGS_BY_FORMAT = {
    "ИПЛ_01_001": {
        "name": "ИПЛ_01_001",
        "branch": "Астана",
        "pricingRule": "Астана",
        "recommendedMarkupName": "Прогиб",
        "recommendedMarkups": [
            {"id": 1, "lowerBound": 0, "upperBound": 49.99, "markupPercent": 10},
            {"id": 2, "lowerBound": 50, "upperBound": 99.99, "markupPercent": 8},
            {"id": 3, "lowerBound": 100, "upperBound": 499.99, "markupPercent": 5},
            {"id": 4, "lowerBound": 500, "upperBound": 999.99, "markupPercent": 4},
            {"id": 5, "lowerBound": 1000, "upperBound": 2999.99, "markupPercent": 3},
            {"id": 6, "lowerBound": 3000, "upperBound": 99999999, "markupPercent": 1},
        ],
        "deflectionPercent": 5.0,
        "includeVAT": True,
        "useMinCompetitor": True,
        "considerStock": False,
    }
}

DASHBOARD = {
    "priceFormats": PRICE_FORMATS,
    "recentPriceLists": GENERATED_PRICE_LISTS,
    "assignments": [
        {
            "format": "ГПЛ_02_001",
            "competitors": len(COMPETITORS_ASSIGNED_BY_FORMAT.get("ГПЛ_02_001", [])),
            "lastUpdate": "21.03.2026",
        },
        {
            "format": "ИПЛ_01_002",
            "competitors": len(COMPETITORS_ASSIGNED_BY_FORMAT.get("ИПЛ_01_002", [])),
            "lastUpdate": "21.03.2026",
        },
    ],
    "activeLists": [
        {"name": "Прямые контракты", "type": "Фикс цена", "items": 0},
        {"name": "Ограничения сверху", "type": "Макс наценка", "items": 0},
        {"name": "Минимальные цены", "type": "Фикс цены", "items": 0},
    ],
    "contractors": [
        {"name": "ТОО Аптека 1", "format": "ГПЛ_02_001", "priceList": "ГПЛ_02_001"},
        {"name": "ТОО Аптека 2", "format": "ГПЛ_02_001", "priceList": "ГПЛ_02_001"},
        {"name": "ТОО Аптека 3", "format": "ГПЛ_02_001", "priceList": "ГПЛ_02_001"},
    ],
}


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
