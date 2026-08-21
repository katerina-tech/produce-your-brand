"""Shared domain vocabulary.

These enums are the contract between the LLM, the supplier dataset and the
matching service. Constraining the LLM to these values is one of the structural
defences against invented capabilities: an extraction that names a method
outside this enum fails validation rather than flowing into supplier matching.
"""

from __future__ import annotations

from enum import StrEnum


class ProductionMethod(StrEnum):
    """Customisation techniques supported by the MVP.

    Eight concrete methods across the four MVP families (engraving, printing,
    embroidery, labels/packaging). Deliberately granular: "printing" is not
    actionable when the choice between screen, digital and foil transfer is
    exactly what the recommendation step exists to make.
    """

    LASER_ENGRAVING = "laser_engraving"
    SCREEN_PRINTING = "screen_printing"
    DIGITAL_PRINTING = "digital_printing"
    PAD_PRINTING = "pad_printing"
    HEAT_TRANSFER = "heat_transfer"
    EMBROIDERY = "embroidery"
    LABEL_APPLICATION = "label_application"
    PACKAGING_PRINT = "packaging_print"


class ProductCategory(StrEnum):
    """Product families the MVP can route."""

    SPORTS_EQUIPMENT = "sports_equipment"
    DRINKWARE = "drinkware"
    APPAREL = "apparel"
    TEXTILES = "textiles"
    BAGS = "bags"
    PACKAGING = "packaging"
    STATIONERY = "stationery"
    ACCESSORIES = "accessories"
    HOMEWARE = "homeware"
    PROMOTIONAL_ITEMS = "promotional_items"


class Priority(StrEnum):
    """What the customer optimises for. Reported, never inferred."""

    COST = "cost"
    SPEED = "speed"
    QUALITY = "quality"
    BALANCED = "balanced"


class Stage(StrEnum):
    """Workflow position. Drives which screen the frontend renders.

    Each ``*_REVIEW``/``SELECTION`` value corresponds to a LangGraph interrupt,
    which is why the frontend needs no workflow logic of its own - it renders
    whatever stage the API reports.
    """

    DRAFT = "draft"
    CLARIFYING = "clarifying"
    BRIEF_REVIEW = "brief_review"
    METHOD_REVIEW = "method_review"
    SUPPLIER_SELECTION = "supplier_selection"
    RFQ_REVIEW = "rfq_review"
    COMPLETED = "completed"
    FAILED = "failed"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
