# Contributing — sharing models, and defending the commons

The unit of contribution is a **model repo**: one directory holding MODEL.md,
its ledgers, and its supporting artifacts. It is already self-contained, so
sharing one is copying a directory and importing it is one command.

    python -m suites.import_model --inspect ../their-model   # preview first
    python -m suites.import_model ../their-model             # then take it

## What you are and are not sharing

**You share the theory.** MODEL.md — premises, falsifiable consequences, the
deletion clause — plus the reasoning artifacts behind it.

**You cannot share a track record.** A record belongs to the instance that made
the predictions. On import, the origin's claims are quarantined to `imported/`
and are never graded as the receiver's own. This is not politeness; a system
whose whole product is "did this predict correctly" cannot let records travel
without the predictions being re-made.

**Publish a mapcard, share the repo on request.** The mapcard is the public
advertisement: aspects, E-span, mechanism one-liner, and record COUNTS only —
never claim text, never reasoning. `python -m suites.reality_map --export --repo
<model>` produces one. The commons indexes cards; repos move peer to peer.

## Moderation: what is and is not reviewed

The standing doctrine is that **bad models die by grading, not by moderation**.
A model that predicts poorly is exposed by its own record; a reviewer's opinion
about whether a theory is *good* adds bias and no information. So there is no
quality review, no editorial board, and no vote on whether an idea deserves to
exist.

That is not the same as no defenses. Grading cannot catch these, so review does:

**1. Schema and licence (automated).** Does the card parse? Does the repo have a
MODEL.md with premises, at least one falsifiable consequence, and a deletion
clause? Is it licensed for redistribution? A model with no falsifier is not
rejected for being wrong — it is rejected for being unable to be wrong, which
makes it undisplayable on a map whose colours mean validation tier.

**2. Payload safety (automated + human).** A model repo is data, but it may
carry code (`explore/*.py`, `tools/*`). Imports never execute anything, and the
importer copies rather than runs — but a reader might. Repos with executable
content are flagged on the card so nobody is surprised.

**3. Privacy and third parties (human).** Models about *people* are the sharp
edge. A model of a public officeholder's incentives is legitimate; a model of a
named private individual is not shareable, whatever its predictive merit. Cards
naming private individuals are refused. This is the one place a human must look.

**4. Record fraud (automated + detectable).** The failure mode unique to this
system: a card claiming a track record the repo cannot support. Because cards
carry counts and repos carry the claims that produced them, a card is checkable
against its own repo — mismatch is grounds for delisting. Nobody's *theory* gets
delisted; only misreported records do.

**5. Impersonation.** Claiming to be someone's instance when you are not.
Instance names are asserted, not verified — so cards carry the name their author
chose and disputes are resolved by the parties, not by us.

## What a reviewer never does

- Judge whether a mechanism is plausible, novel, or well-written
- Reject a model for contradicting another model, including a popular one
- Reject a model for being about a contentious subject
- Rank models by anything except their own graded record

Two cards claiming the same region with opposite records is the map working.

## Delisting and its reversal

A card is delisted only for: failing schema, misreporting its record, naming a
private individual, or a licence violation. Delisting removes the card from the
index; it does not delete the model, and the repo remains wherever its author
keeps it. Every delisting is logged with its reason, and reinstatement follows
from fixing the specific defect — not from appeal.

**Refuted models stay listed.** A model whose consequences failed and which
honoured its deletion clause is a tombstone, and tombstones are the most
valuable content on a map: knowing a mechanism does *not* operate in a region is
a finding. Refutation is a result, never a reason for removal.

## The honest state

The commons index does not exist yet. Mapcards, the export command, and the
import path all work today, so models can already be shared peer to peer. What
is missing is discovery — a place to publish a card so others know a model
exists. Until then, sharing works by sending someone a directory.
