"""The buyer: what takes an invoice in, and what it says of it afterwards.

    from mockeinvoice.buyer import Buyer

    buyer = Buyer()
    held = buyer.receive(xml)           # or TurnedAway, saying why
    answer = buyer.answer(held.id, "UQ", reasons=[{"code": "REF"}], actions=["PIN"])
    answer.xml                          # the Invoice Response, as sent

A document is taken in only if it is `valid`. One that is `invalid` is turned
away with what was found, and so is one that is `not judged`: a document this
package has fatal rules left to build for is not let in as though it had
passed them.

What the buyer says afterwards is a Peppol Invoice Response, and Peppol's
guide to it has rules about the order responses come in that are in no
Schematron file (`OP-BR111-R004`, `-R005`, `-R012`). `PROCESS` names them,
and `Buyer.answer` keeps to them unless it is told to `force` one through,
which is how to rehearse a buyer who does not.

Nothing happens by itself after a document is received. Each later status is
asked for.
"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from . import response as _response
from . import specification as _specification
from .model import Document, Finding, Refused
from .response import Answered, Party, Response, Status
from .rules import Report, check, check_response
from .rules.peppol import PROFILES
from .ubl import parse_tree

GUIDE = ("https://docs.peppol.eu/poacc/upgrade-3/profiles/63-invoiceresponse/"
         "#invoice-response-process-rules")
# The order a status advances in. Any may be first and any may be left out.
ORDER = ("AB", "IP", "UQ", "CA", "RE", "AP", "PD")
# The guide's rules about that order, each in our words.
PROCESS = {
    "OP-BR111-R004": "nothing follows a rejection (RE) or a payment in full (PD)",
    "OP-BR111-R005": "only paid (PD) follows accepted (AP)",
    "OP-BR111-R012": "a status does not go back in the order %s, and only under query (UQ) "
                     "and a part payment come twice" % ", ".join(ORDER),
}
# When the buyer acknowledges a document without being asked: where the
# document's profile makes a response a required step, whatever the profile,
# or not at all.
ANSWERS = ("required", "always", "never")


class TurnedAway(Exception):
    """A document the buyer did not take in, and why.

    `code` is the refusal's own (`NOT-XML`, `SPECIFICATION`) where the document
    could not be read as one that is taken, and `INVALID` or `NOT-JUDGED`
    where it was read and its `report` is why.
    """

    def __init__(self, code: str, reason: str, report: Optional[Report] = None):
        super().__init__(reason)
        self.code, self.reason, self.report = code, reason, report


class NotSaid(Exception):
    """A response the buyer will not give. `code` is the guide's rule where
    one stands in the way, and `findings` what the response's own rules found
    where they do."""

    def __init__(self, code: str, reason: str, findings: Sequence[Finding] = ()):
        super().__init__(reason)
        self.code, self.reason, self.findings = code, reason, list(findings)


@dataclass
class Sent:
    """One Invoice Response the buyer gave."""
    id: str
    invoice: str                            # the id of the document it answers
    code: str
    partial: bool                           # a payment in part: PD with the reason PPD
    forced: bool                            # given against the guide's order
    xml: bytes
    # What the response's own rules had to say that did not stop it.
    warnings: List[Finding] = field(default_factory=list)
    # What became of sending it to the seller: {"to": url, "status": 200},
    # {"to": url, "error": "..."}, or None where there was nowhere to send it.
    delivery: Optional[dict] = None


@dataclass
class Held:
    """A document the buyer took in."""
    id: str
    xml: bytes
    document: Document
    report: Report
    received: str                           # when, as an ISO 8601 date and time
    responses: List[Sent] = field(default_factory=list)

    @property
    def number(self) -> str:
        return self.document.text("BT-1")

    @property
    def profile(self) -> str:
        """Peppol's billing profile, `01` or `02`; "" for XRechnung."""
        if self.report.specification != "peppol":
            return ""
        return PROFILES.get(self.document.text("BT-23").strip(), "")

    @property
    def status(self) -> str:
        """The last thing said of it, or "" if nothing has been."""
        return self.responses[-1].code if self.responses else ""


Clarification = Union[str, dict]


def clarifications(given: Sequence[Clarification], list_id: str) -> List[Status]:
    """Reasons or actions as `Status`es: a bare code, or a dict with any of
    `code`, `text` and `conditions` (pairs of a business term and a value)."""
    made = []
    for one in given:
        if isinstance(one, str):
            one = {"code": one}
        unknown = sorted(set(one) - {"code", "text", "conditions"})
        if unknown:
            raise NotSaid("REQUEST", "a clarification has code, text and conditions, "
                                     "not %s" % ", ".join(unknown))
        made.append(Status(reason_code=one.get("code", ""),
                           list_id=list_id if one.get("code") else "",
                           reason=one.get("text", ""),
                           conditions=[(str(term), str(value))
                                       for term, value in one.get("conditions", ())]))
    return made


def out_of_order(before: Sequence[Sent], code: str, partial: bool) -> Optional[str]:
    """The guide's rule that a response would break after those before it, or
    None. A code that is not one of the seven is left to the response's own
    rules, which name it."""
    if not before or code not in ORDER:
        return None
    if any(said.code == "RE" or (said.code == "PD" and not said.partial) for said in before):
        return "OP-BR111-R004"
    known = [said for said in before if said.code in ORDER]
    if not known:
        return None
    furthest = max(known, key=lambda said: ORDER.index(said.code))
    if furthest.code == "AP" and code != "PD":
        return "OP-BR111-R005"
    was, now = ORDER.index(furthest.code), ORDER.index(code)
    if now < was or (now == was and code not in ("UQ", "PD")):
        return "OP-BR111-R012"
    return None


class Buyer:
    """A buyer's system: the documents it holds and what it has said of them.

    `deliver` is called with each response's XML and returns what became of
    sending it (see `Sent.delivery`); without one, responses are kept and not
    sent. `now` is the clock.
    """

    def __init__(self, answers: str = "required",
                 deliver: Optional[Callable[[bytes], dict]] = None,
                 now: Optional[Callable[[], datetime.datetime]] = None):
        if answers not in ANSWERS:
            raise ValueError("answers is one of %s, not %r" % (", ".join(ANSWERS), answers))
        self.answers = answers
        self.deliver = deliver
        self.now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.invoices: Dict[str, Held] = {}
            self.responses: Dict[str, Sent] = {}
            # What was turned away: (when, code, reason), oldest first.
            self.turned_away: List[Tuple[str, str, str]] = []

    def stamp(self) -> str:
        return self.now().replace(microsecond=0, tzinfo=None).isoformat()

    # -- taking a document in -----------------------------------------------------------

    def receive(self, data: Union[bytes, str]) -> Held:
        """Take a document in, or raise `TurnedAway`."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        with self.lock:
            try:
                held = self.judged(raw)
            except TurnedAway as away:
                self.turned_away.append((self.stamp(), away.code, away.reason))
                raise
            self.invoices[held.id] = held
            if held.report.specification == "peppol" and (
                    self.answers == "always"
                    or (self.answers == "required" and held.profile == "02")):
                self.answer(held.id, "AB")
            return held

    def judged(self, raw: bytes) -> Held:
        try:
            document, findings, sent = parse_tree(raw)
            specification = _specification.identify(document)
        except Refused as refused:
            raise TurnedAway(refused.code, refused.reason)
        report = check(document, specification, findings, sent)
        if report.verdict == "invalid":
            failures = report.failures
            raise TurnedAway("INVALID", "the document is invalid: %d finding%s, the first %s "
                             "at %s" % (len(failures), "" if len(failures) == 1 else "s",
                                        failures[0].code, failures[0].path), report)
        if report.verdict != "valid":
            raise TurnedAway("NOT-JUDGED", "nothing was found wrong with the document, but "
                             "%d fatal rule%s that could apply to it %s not built, so it was "
                             "not judged and is not taken in: %s"
                             % (report.unasked, "" if report.unasked == 1 else "s",
                                "is" if report.unasked == 1 else "are",
                                ", ".join(not_run(report))), report)
        return Held(str(len(self.invoices) + 1), raw, document, report, self.stamp())

    # -- answering it -------------------------------------------------------------------

    def answer(self, invoice: str, code: str, reasons: Sequence[Clarification] = (),
               actions: Sequence[Clarification] = (), note: str = "",
               force: bool = False) -> Sent:
        """Say something of a document held, or raise `NotSaid`.

        The response is written, held to the Invoice Response's rules and to
        the guide's order, kept, and sent to the seller if there is somewhere
        to send it. `force` gives a response the guide's order forbids; it
        does not give one the response's own rules fail.
        """
        with self.lock:
            held = self.invoices.get(invoice)
            if held is None:
                raise NotSaid("NO-SUCH-INVOICE", "no document %r is held" % invoice)
            if held.report.specification != "peppol":
                raise NotSaid("NO-RESPONSE", "document %s is %s, which has no response "
                              "message: it got its verdict and gets nothing after it"
                              % (invoice, _specification.NAMES[held.report.specification]))
            statuses = (clarifications(reasons, _response.REASON_LIST)
                        + clarifications(actions, _response.ACTION_LIST))
            partial = code == "PD" and any(
                status.reason_code == "PPD" and status.list_id == _response.REASON_LIST
                for status in statuses)
            broken = out_of_order(held.responses, code, partial)
            if broken and not force:
                raise NotSaid(broken, "%s cannot follow %s: %s (%s). \"force\" sends it anyway"
                              % (code, ", ".join(said.code for said in held.responses),
                                 PROCESS[broken], broken))
            identifier = str(len(self.responses) + 1)
            xml = _response.write(self.written(held, identifier, code, statuses, note))
            _read, findings, sent = _response.parse_tree(xml)
            report = check_response(sent, findings)
            failures = report.failures
            if failures:
                raise NotSaid("INVALID", "the response would fail its own rules: %s"
                              % ", ".join(sorted({f.code for f in failures})), failures)
            said = Sent(identifier, invoice, code, partial, bool(broken), xml,
                        list(report.findings))
            self.responses[identifier] = said
            held.responses.append(said)
        if self.deliver is not None:
            said.delivery = self.deliver(xml)
        return said

    def written(self, held: Held, identifier: str, code: str, statuses: List[Status],
                note: str) -> Response:
        """The response to one document: from its buyer to its seller, about
        it by number, date and type, under the profile its own calls for."""
        document, now = held.document, self.now()
        return Response(
            profile=(_response.BILLING_WITH_RESPONSE if held.profile == "02"
                     else _response.PROFILE),
            id="IR-%s" % identifier.rjust(6, "0"),
            issue_date=now.date().isoformat(), issue_time=now.strftime("%H:%M:%S"),
            note=note,
            sender=Party(endpoint=document.term("BT-49"), identifier=document.term("BT-46"),
                         name=document.text("BT-44")),
            receiver=Party(endpoint=document.term("BT-34"), identifier=document.term("BT-29"),
                           name=document.text("BT-27")),
            code=code, effective_date=now.date().isoformat(), statuses=statuses,
            document=Answered(id=document.text("BT-1"), issue_date=document.text("BT-2"),
                              type_code=document.text("BT-3")))


def not_run(report: Report) -> List[str]:
    """The fatal rules that could apply to a document and are not built."""
    return sorted(identifier for rules in report.not_built.values()
                  for identifier, flag in rules.items() if flag == "fatal")
