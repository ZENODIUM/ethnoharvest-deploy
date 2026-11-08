"""Source registry and jurisdiction rule records for HarvestOps cautions.

Every record was looked up on 2026-11-07. `excerpt` holds verbatim text only where we read the primary document; otherwise
`summary` describes what secondary sources report and the status says that it needs confirmation. Nothing here is legal
advice, a permit, or a statement of current law: national rules change and only the competent authority can confirm them.
"""
from __future__ import annotations

CHECKED = "2026-11-07"

SOURCES: dict[str, dict] = {
    "who-gacp-2003": {
        "title": "WHO guidelines on good agricultural and collection practices (GACP) for medicinal plants (2003)",
        "publisher": "World Health Organization", "url": "https://www.who.int/publications/i/item/9241546271",
        "kind": "guidance", "binding": False,
        "summary": "Advisory technical guidance on obtaining medicinal plant material of good quality, covering cultivation, wild "
                   "collection and post-harvest handling. It is not a legal requirement.",
    },
    "ema-gacp": {
        "title": "EMA Guideline on Good Agricultural and Collection Practice (GACP) for starting materials of herbal origin "
                 "(EMEA/HMPC/246816/2005; Revision 1 adopted by HMPC in 2025)",
        "publisher": "European Medicines Agency, HMPC",
        "url": "https://www.ema.europa.eu/system/files/documents/scientific-guideline/hmpc-guideline-gacp-may-2025_en.pdf",
        "kind": "guidance", "binding": False,
        "summary": "Quality expectations for herbal starting materials used in EU medicinal products, covering collection or "
                   "cultivation, harvest and primary processing. Relevant when the buyer supplies the EU medicines market.",
    },
    "fairwild-3": {
        "title": "FairWild Standard: Version 3.0 (approved 19 December 2023)", "publisher": "FairWild Foundation",
        "url": "https://www.fairwild.org/s/FairWildStandard-V3-FINAL.pdf", "kind": "voluntary-standard", "binding": False,
        "excerpts": {
            "p1": "Principle 1: Wild harvesting supports conservation of the collected species. Desired outcome: Harvesting of wild "
                  "resources is conducted in a manner and on a scale that maintains populations and species over time",
            "p5": "Principle 5: Benefits and respect for customary rights of wild collectors and their communities are ensured",
            "p6": "Principle 6: Harvest and trade of wild resources are legally compliant",
        },
        "summary": "Voluntary certification standard (7 principles, 24 criteria). Replaces Version 2.0 (2010).",
    },
    "cites-appendices": {
        "title": "CITES Appendices I, II and III", "publisher": "CITES Secretariat", "url": "https://cites.org/eng/app/appendices.php",
        "kind": "trade-listing", "binding": True,
        "summary": "International trade in specimens of Appendix II species requires export permits issued after a legal-acquisition "
                   "and non-detriment finding by the exporting country. Annotations decide which parts and derivatives are covered.",
    },
    "speciesplus": {
        "title": "Species+ (CITES and CMS listings)", "publisher": "UNEP-WCMC / CITES Secretariat", "url": "https://speciesplus.net/",
        "kind": "trade-listing", "binding": False, "summary": "Live listing lookup used for the passport's CITES field.",
    },
    "cites-livelihoods-jatamansi": {
        "title": "CITES & livelihoods fact sheet: Jatamansi in Nepal (2022)", "publisher": "CITES Secretariat",
        "url": "https://cites.org/sites/default/files/eng/prog/Livelihoods/case_studies/2022/CITES_%26_livelihoods_fact_sheet_Jatamansi%20Nepal.pdf",
        "kind": "agency-report", "binding": False,
        "summary": "Reports Nepal as the main exporting country of jatamansi, listed in CITES Appendix II in 1997, and describes the "
                   "effect of national export restrictions on unprocessed rhizome.",
    },
    "traffic-jatamansi": {
        "title": "Jatamansi trade from Nepal", "publisher": "TRAFFIC",
        "url": "https://traffic.org/what-we-do/thematic-issues/promoting-sustainable-trade/jatamansi-trade-from-nepal",
        "kind": "ngo-report", "binding": False,
        "summary": "Programme page on sustainable production and trade of CITES Appendix II-listed jatamansi in Nepal.",
    },
    "ansab-jatamansi": {
        "title": "Jatamansi factsheet", "publisher": "ANSAB (Asia Network for Sustainable Agriculture and Bioresources)",
        "url": "https://ansab.org.np/wp-content/uploads/2024/02/jatamansi.pdf", "kind": "ngo-guidance", "binding": False,
        "summary": "Field guidance reported as: leave a small part of the rhizome for regeneration, harvest rotationally, and do not "
                   "harvest without a collection permit.",
    },
    "cites-pc16-prunus": {
        "title": "CITES Plants Committee PC16 Doc. 10.2: Review of Significant Trade (includes Prunus africana)",
        "publisher": "CITES Plants Committee", "url": "https://cites.org/sites/default/files/eng/com/pc/16/E-PC16-10-02.pdf",
        "kind": "agency-report", "binding": False,
        "summary": "Significant Trade Review covering 1995-2003 trade data; the PC16 working group recommended that Cameroon review its "
                   "export quota and set a conservative reduced quota for Prunus africana parts and derivatives.",
    },
    "itto-prunus-cameroon": {
        "title": "Critical study of guidance for a national Prunus africana management plan, Cameroon (2010)",
        "publisher": "ITTO-CITES programme",
        "url": "https://www.itto.int/files/user/cites/cameroon/CRITICAL%20STUDY%20OF%20PRUNUS%20AFRICANA%20MANAGEMENT%20PLAN%20CAMEROON_Julius_28_11_2010.pdf",
        "kind": "agency-report", "binding": False,
        "summary": "Background on management inventories and non-detriment findings used to set Cameroon's bark export quotas.",
    },
    "ethiopia-1065-2018": {
        "title": "Forest Development, Conservation and Utilization Proclamation No. 1065/2018 (Federal Negarit Gazette, Ethiopia)",
        "publisher": "Federal Democratic Republic of Ethiopia",
        "url": "https://www.metaappz.com/References/ethiopian_laws/federal/pr_1065_2018/en/pdf",
        "kind": "law", "binding": True,
        "summary": "Federal forest law; secondary sources report it expanded community forest use and management rights. We did not "
                   "verify a provision specific to frankincense tapping. Text hosted by a third party.",
    },
    "agris-khaya-2008": {
        "title": "Impacts of bark and foliage harvest on Khaya senegalensis (Meliaceae) reproductive performance in Benin",
        "publisher": "Gaoue & Ticktin (2008), indexed in FAO AGRIS", "url": "https://agris.fao.org/search/en/records/65de2f484c5aef494fdac59f",
        "kind": "study", "binding": False,
        "summary": "Reports that pruning (foliage harvest) significantly decreased fruit production in the Sudanian region but not in the "
                   "Sudano-Guinean region.",
    },
}

# Jurisdiction records. status: "documented-requirement" (binding source located), "reported-requires-confirmation" (secondary
# reports only), or "no-credible-source-found".
JURISDICTION_RULES: list[dict] = [
    {"id": "np-jatamansi-export", "jurisdiction": "nepal", "species": "Nardostachys jatamansi", "organs": ["rhizome", "root"],
     "status": "reported-requires-confirmation", "topic": "Export of unprocessed rhizome",
     "statement": "Reported restriction: export of unprocessed jatamansi rhizome has been prohibited under Nepal's forest legislation, "
                  "while processed products such as distilled oil are traded under regulation.",
     "next": "Confirm the current rule and any collection permit conditions with the Division Forest Office and the Department of "
             "Forests and Soil Conservation before planning sale or export.",
     "sources": ["cites-livelihoods-jatamansi", "traffic-jatamansi", "ansab-jatamansi"]},
    {"id": "cm-prunus-quota", "jurisdiction": "cameroon", "species": "Prunus africana", "organs": ["bark"],
     "status": "reported-requires-confirmation", "topic": "Export quota and non-detriment finding",
     "statement": "Bark exports are managed through CITES export quotas based on non-detriment findings and management inventories; "
                  "quotas have changed over time following CITES reviews.",
     "next": "Ask the CITES Management Authority (forestry ministry) for the current quota, the allocation for your area and the "
             "management unit's inventory status.",
     "sources": ["cites-pc16-prunus", "itto-prunus-cameroon", "cites-appendices"]},
    {"id": "et-forest-law", "jurisdiction": "ethiopia", "species": None, "organs": None,
     "status": "documented-requirement", "topic": "Federal forest law applies",
     "statement": "Collection in forests falls under the Forest Development, Conservation and Utilization Proclamation No. 1065/2018. "
                  "We did not locate a provision specific to frankincense tapping.",
     "next": "Confirm tapping rights, concession or community forest agreements with the regional forest authority.",
     "sources": ["ethiopia-1065-2018"]},
    {"id": "bj-none", "jurisdiction": "benin", "species": None, "organs": None,
     "status": "no-credible-source-found", "topic": "National collection rules",
     "statement": "We have not yet located an official source for collection rules that apply to this plant part in Benin.",
     "next": "Ask the national forestry administration which permits apply to bark and foliage collection.",
     "sources": []},
]

# Regulatory principles that apply whatever the species (shown as general context, never as a verdict).
GENERAL = [
    {"id": "gen-legal", "topic": "Legal compliance is part of sustainable collection", "sources": ["fairwild-3"], "excerpt_key": "p6",
     "statement": "Voluntary standards treat legal compliance at local, national and international level as a precondition.",
     "next": "List the authorisations your collection needs and attach them to the passport."},
    {"id": "gen-rights", "topic": "Customary rights and benefit sharing", "sources": ["fairwild-3"], "excerpt_key": "p5",
     "statement": "Collection should respect collectors' and communities' customary rights and share benefits fairly.",
     "next": "Record how consent and benefit sharing were agreed with the community that holds rights to the site."},
    {"id": "gen-quality", "topic": "Collection and post-harvest quality practice", "sources": ["who-gacp-2003", "ema-gacp"],
     "statement": "GACP guidance covers identification, collection practice, drying, storage and documentation of herbal starting materials.",
     "next": "Keep identification, drying and storage records per lot; ask the buyer which GACP expectations apply."},
]


def source(sid: str) -> dict:
    s = SOURCES[sid]
    return {"title": s["title"], "url": s["url"], "kind": s["kind"], "publisher": s["publisher"], "checked": CHECKED,
            "excerpt": None, "summary": s.get("summary")}
