"""The approved quotation request, as an email somebody can actually send.

Two properties hold this together, and both are structural rather than
enforced by a check:

**Nothing here calls a model.** The body is assembled from the ``RFQ`` the user
already approved at the last gate. A model asked to "summarise" it could
shorten a quantity, soften a deadline or invent a price, and the user would be
sending text they never saw. Approval that does not survive to the outgoing
message is not approval.

**Nothing here sends.** This produces a subject, a body and links that open the
user's own mail client with both filled in. The buyer stays the sender, which
is the whole legal posture of the product: no contact data is stored, so GDPR
Art. 14 does not arise, and UWG §7 is not engaged by a platform that never
contacts anybody.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, Field

GMAIL_COMPOSE = "https://mail.google.com/mail/"

# Browsers and Gmail both stop honouring very long URLs, and the failure is
# silent truncation - a half-written email in the compose window. Past this the
# interface offers copying instead, which has no limit.
MAX_URL_LENGTH = 7000


class OutreachEmail(BaseModel):
    """A ready-to-send message, plus the ways to open it.

    ``to`` is deliberately optional and usually empty: this product holds no
    supplier email addresses, because holding them would be the very processing
    it avoids. The address is the one thing the person sending supplies.
    """

    model_config = ConfigDict(extra="forbid")

    to: str = Field(default="", description="Empty unless the sender supplied one.")
    subject: str
    body: str

    @property
    def gmail_url(self) -> str:
        """A Gmail compose window, pre-filled. Opens; never sends."""
        query = urlencode(
            {"view": "cm", "fs": "1", "to": self.to, "su": self.subject, "body": self.body},
            quote_via=quote,
        )
        return f"{GMAIL_COMPOSE}?{query}"

    @property
    def mailto_url(self) -> str:
        """The same message for whatever mail client this machine prefers."""
        query = urlencode({"subject": self.subject, "body": self.body}, quote_via=quote)
        return f"mailto:{quote(self.to)}?{query}"

    @property
    def fits_in_a_url(self) -> bool:
        """Whether the links can carry this message without being truncated.

        Reported rather than worked around: an interface that silently offered
        a link which drops the last paragraph would be worse than one that says
        to copy the text instead.
        """
        return max(len(self.gmail_url), len(self.mailto_url)) <= MAX_URL_LENGTH
