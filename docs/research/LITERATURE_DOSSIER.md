# EthnoHarvest AI: literature dossier

Compiled 2026-11-07. This is a research note for EthnoHack 2026 (Sustainable Harvesting / ethnopharmacology track).

**Confidence labels**
- **verified-from-fulltext**: I read the value in the full text of the paper.
- **verified-from-abstract**: I read the value in the official abstract only, through Crossref, OpenAlex or Europe PMC metadata.
- **secondary-source**: the claim comes from another paper, a review, a repository summary or a search-engine snippet. I did not see the primary source.
- **unverified**: the claim could not be checked.

**Access notes.** Full-text PDFs came from author-hosted copies of the publisher versions:
- Ghimire et al. 2008: `oliviergimenez.github.io/pubs/Ghimireetal2007JAE.pdf`
- Schmidt et al. 2011, Gaoue & Ticktin 2010 and Gaoue et al. 2011: `volweb.utk.edu/~ogaoue/papers/`
- Smith-Hall et al. 2023, Smith-Hall et al. 2025 and Gowthami et al. 2021: Europe PMC full-text XML.

The following sites returned 403 or a bot challenge, so I could not read them directly: Wiley, ScienceDirect, cites.org, iucnredlist.org and HAL.

Machine-readable values are in `literature_values.json` (57 rows, verified only) and `open_datasets.json` (19 rows).

---

## 1. Flagship species: *Nardostachys jatamansi* (syn. *N. grandiflora*), jatamansi / spikenard

### 1.1 Citation check
**Ghimire SK, Gimenez O, Pradel R, McKey D, Aumeeruddy-Thomas Y (2008).** Demographic variation and population viability in a threatened Himalayan medicinal and aromatic herb *Nardostachys grandiflora*: matrix modelling of harvesting effects in two contrasting habitats. *Journal of Applied Ecology* 45(1): 41–51. DOI: [10.1111/j.1365-2664.2007.01375.x](https://doi.org/10.1111/j.1365-2664.2007.01375.x)
- Crossref confirms the title, journal, volume 45 and pages 41–51. OpenAlex marks it as hybrid open access. The PDF header reads "Journal of Applied Ecology 2008, 45, 41–51" (© 2007). **verified-from-fulltext**
- Taxonomy: GBIF treats *N. grandiflora* Wall. ex DC. as a synonym of the accepted name ***Nardostachys jatamansi* (D.Don) DC.** (Caprifoliaceae; older sources place it in Valerianaceae). COMPADRE v6.26.3.0 stores these matrices under *Nardostachys jatamansi*. **verified** (GBIF species-match API and the local COMPADRE metadata)

### 1.2 Study design (all verified-from-fulltext, pp. 42–43)
| Item | Detail | Location |
|---|---|---|
| Site | Shey-Phoksundo National Park and its buffer zone, NW Nepal. Coordinates 29°05′–29°12′ N, 82°40′–82°55′ E. Trans-Himalayan climate, 450–800 mm rain per year. | p.42, Study populations |
| Elevation | 3800–4200 m, above the tree line | p.43 |
| Habitats | (1) Rocky outcrop, inside the park: soil pH 6.9–7.7, moisture 18–28%, organic matter 2.5–6.5%. (2) Alpine meadow: pH 4.9–5.5, moisture 39–45%, organic matter 12–15%. | p.43 |
| Populations | Outcrop inside the park, with the experimental harvest. Unharvested meadow inside the park. Commercially harvested meadow in the buffer zone, less than 4 km from a village. | p.43 |
| Plots | Outcrop: 3 plots × 5 belt transects (5×1 m) × 5 subplots of 1 m², so 25 subplots per plot. Meadow: 2 plots × 3–4 transects. About 10–15 clumps per subplot in 1998. | p.43 |
| Harvest treatments | Applied in September 1998, at the end of the growing season, by local **amchi** (Tibetan-medicine practitioners) using their own selective method. Treatments removed **0 (control), 10, 25, 50 and 75 % of rhizomes from mature clumps**, with 5 replicates per plot. Harvest was applied **once**. Levels above 10% exceed usual amchi practice. The commercially harvested meadow had an unmeasured harvest level, which the authors describe as ">25%". | p.43 |
| Census | Monthly from June to September in 1999–2000, then annually (June/July) until 2002. The commercially harvested meadow was monitored only for 1999–2000 because tags were lost. | p.43 |
| Stage classes (Table 1, p.44) | Seedling (Sd, cotyledon leaves). Juvenile (J, 1 ramet). A1 (1–3 ramets), A2 (4–6), A3 (7–9), A4 (≥10). The plant is caespitose and clonal ("phalanx" growth). An individual is the whole clump of connected ramets. | Table 1 |
| Fecundity | Stage-specific fecundity = (inflorescences ÷ individuals in the stage) × seeds per inflorescence × probability of seedling recruitment. Recruitment probability came from sowing 100 seeds per 1 m² subplot. Recruitment was assumed equal across harvest treatments within a habitat. | p.43 |
| Analysis | Annual matrices for 1999–2000, 2000–01 and 2001–02. Weighted mean matrices. Bootstrap percentile 95% CI. Elasticity, fixed LTRE, transient dynamics and stochastic simulation. Software: MATLAB 5.3 and DEMOGRAPHE (Nantel 2004). | p.43–44 |

### 1.3 Reported population growth rates (λ), all verified-from-fulltext
**Outcrop, harvest experiment, 1999–2000 transition** (p.46 text; 95% CIs are shown only graphically in Fig. 2a):

| Treatment | λ (1999–2000) |
|---|---|
| 0% (control) | **1.014** |
| 10% | **0.928** |
| 25% | **0.838** |
| 50% | **0.779** |
| 75% | **0.637** |

- In 1999–2000, every harvest level differed significantly from the control (95% CIs did not overlap).
- In 2000–01 and 2001–02, λ "gradually increased in all treatments". It stayed significantly below the control at every level except 10%.
- The Discussion (p.50) adds that "at all harvesting levels λ was still <1 at the end of the study".
- **Unharvested meadow:** λ = **1.12–1.17** across the three years, all significantly above 1.
- **Outcrop control:** λ = **1.01–1.04**, significantly above 1 only in 2001–02. Meadow and outcrop CIs did not overlap in 1999–2000 and 2000–01.
- **Commercially harvested meadow:** a λ for 1999–2000 is plotted in Fig. 2b, but the text does not state the number. **unverified (not extractable)**
- Stochastic λ was "very similar" to deterministic λ. The values are in Table S1, which is in the supplementary material and was **not accessed**.

### 1.4 Elasticity and LTRE (verified-from-fulltext, p.46–47; Figs 3–4)
- **Outcrop control:** stasis (S) made the largest elasticity contribution. Large size classes dominated.
- **Unharvested meadow:** progression (P, vegetative growth) contributed more than stasis. Fecundity contributed more than in the outcrop. Seedling and juvenile contributions were "almost double" those in the outcrop.
- **As harvest intensity rose:** survival of progressively smaller adults gained elasticity, because amchi harvest targets large clumps.
- **Fecundity:** had the lowest influence on λ in all treatments.
- **LTRE, outcrop harvest:** harvest lowered λ mainly through **progression and stasis**, with the largest negative contributions at the highest harvest levels. Retrogression contributions were positive, meaning more shrinkage after harvest.
- **LTRE, meadow vs outcrop:** only stasis favoured the outcrop. Fecundity, progression and retrogression explained the meadow's higher λ.
- **Schmidt et al. 2011** (p.819, Fig. 4) classify *N. grandiflora* as a species whose most harvest-affected vital rates have both high elasticity and high negative LTRE contributions, which indicates low sustainability. **verified-from-fulltext**

### 1.5 Stochastic, PVA and recovery results (verified-from-fulltext, p.47–48)
- **Transient projections (1999–2000 matrices, 15 years):**
  - If the outcrop were harvested every year at more than 25%, it would face a "high probability of extinction within 15 years".
  - Even at 10% harvest, a rapid decline was projected.
  - The commercially harvested meadow declined even faster.
- **Stochastic simulation (1000 runs × 100 years):**
  - Unharvested populations in either habitat: **0 extinctions**.
  - **Extinction probability at 10, 25, 50 and 75% harvest: 0.14, 0.68, 0.77 and 0.87.**
- **Deterministic recovery after a single harvest:**
  - Outcrop returns to its initial size in **5 years after 10%** harvest. The Summary says "≈5".
  - Outcrop recovery takes **17 years after 25%** and **33 years after 75%** harvest.
  - The commercially harvested meadow recovers in **6 years**.

### 1.6 Other demographic facts (verified-from-fulltext)
- **In-situ seedling recruitment** (p.44): outcrop 4.7 ± 3.3%, meadow 16.4 ± 5.7% (mean ± SD), F(1,24) = 49.68, P = 0.0001. Table 3 gives per-year values: outcrop 5.0, 3.8 and 5.4%; meadow 16.4, 13.2 and 19.6%.
- **Flowering frequency** (Table 3):

  | Population | 1999 | 2000 | 2001 |
  |---|---|---|---|
  | Outcrop | 25.64% | 22.84% | 17.56% |
  | Meadow | 51.16% | 39.62% | 30.65% |

- **Seed set per inflorescence:** did not differ between habitats. Meadow seeds were heavier (Table 3).
- **Survival** (p.45): adult survival in unharvested subplots was 88–100%. Seedling survival was 46–78% and juvenile survival 68–90%. Harvest raised adult mortality, partly through trampling and soil destabilisation on steep outcrops. This effect was significant only in the first year.
- **Ramets per individual:** outcrop 6.58 ± 3.43, meadow 4.58 ± 3.20.
- **Amchi harvest volume** (p.50): about 6.0 kg per amchi per year, at harvest rates that usually do not exceed 10%.

### 1.7 Management recommendations (verified-from-fulltext, Summary point 5 and pp.49–50)
- Harvest **less than 10% of rhizomes in outcrop** populations and **less than 25% in meadow** populations.
- Leave **at least 5 years** between successive harvests.
- Outcrop populations should be used "only at strictly controlled rates for local healthcare needs". Commercial harvesting of outcrops "would lead to their rapid extinction".
- Promote cultivation and in-situ enrichment planting, with amchi as partners. Continue monitoring.

### 1.8 Related and later Nardostachys work
| Citation | DOI | What it adds | Confidence |
|---|---|---|---|
| Ghimire SK, McKey D, Aumeeruddy-Thomas Y (2005) Conservation of Himalayan medicinal plants: harvesting patterns and ecology of two threatened species, *N. grandiflora* and *Neopicrorhiza scrophulariiflora*. *Biol Conserv* 124: 463–475 | [10.1016/j.biocon.2005.02.005](https://doi.org/10.1016/j.biocon.2005.02.005) | Same Shey-Phoksundo system and the amchi selective-harvest experiment that Ghimire 2008 builds on (p.43 "further details of the experiment are given by Ghimire et al. 2005"). Per secondary summaries, low harvest levels had a positive effect on density, while recruitment and survival fell as harvest rose. | Citation verified via Crossref. Content: **secondary-source** (abstract elided by the publisher in OpenAlex and Semantic Scholar) |
| Ghimire SK, McKey D, Aumeeruddy-Thomas Y (2004) Heterogeneity in ethnoecological knowledge and management of medicinal plants in the Himalayas of Nepal. *Ecology and Society* 9(3): 6 | (no DOI; ecologyandsociety.org/vol9/iss3/art6) | Companion paper on harvester types (commercial, amchi, non-specialist) | Citation verified-from-fulltext (Ghimire 2008 reference list) |
| Larsen HO (2005) Impact of replanting on regeneration of the medicinal plant *Nardostachys grandiflora* DC. *Econ Bot* 59(3): 213–220 | [10.1663/0013-0001(2005)059[0213:IOROROR]2.0.CO;2](https://doi.org/10.1663/0013-0001(2005)059[0213:IOROROR]2.0.CO;2) | Smith-Hall et al. 2023 report that replanting the upper plant parts plus 2 cm of rhizome gave the fastest regeneration and rhizome biomass growth. Smith-Hall et al. 2025 call this a "regenerative cultivating-while-collecting technique". | Citation verified via Crossref. Content: **secondary-source** |
| Olsen CS (2005) Trade and conservation of Himalayan medicinal plants: *N. grandiflora* and *N. scrophulariiflora*. *Biol Conserv* 125: 505–514 | [10.1016/j.biocon.2005.04.013](https://doi.org/10.1016/j.biocon.2005.04.013) | Cited by Smith-Hall 2023 for Nepal supplying 82% of annual global production | Citation verified (Crossref). Claim: secondary-source |
| Smith-Hall C, Pyakurel D, Meilby H, Pouliot M, Ghimire PL, Ghimire SK, et al. (2023) The sustainability of trade in wild plants: a data-integration approach tested on critically endangered *N. jatamansi*. *PNAS Nexus* 2(11): pgad328. PMC10635652 | [10.1093/pnasnexus/pgad328](https://doi.org/10.1093/pnasnexus/pgad328) | Up-scaling of trade versus sustainable yield, using Ghimire 2008 (10% or 25% per 5-year rotation) and Larsen 2005 (100% with replanting) as harvest scenarios. Details in §5. | **verified-from-fulltext** |
| Chauhan HK, Oli S, Bisht AK, Meredith C, Leaman DJ (2021) Review of the biology, uses and conservation of the critically endangered endemic Himalayan species *N. jatamansi*. *Biodivers Conserv* 30: 3315–3333 | [10.1007/s10531-021-02269-6](https://doi.org/10.1007/s10531-021-02269-6) | Main recent review. Not open access, contents not read. | Citation verified (Crossref) |
| Poudeyal MR, Meilby H, Shrestha BB, Ghimire SK (2019) Harvest effects on density and biomass of *Neopicrorhiza scrophulariiflora* vary along environmental gradients in the Nepalese Himalayas. *Ecol Evol* 9: 7726–7740 | [10.1002/ece3.5355](https://doi.org/10.1002/ece3.5355) | Sister species from the same trade. Open-access commercial collection of 35–465 kg of dried rhizome per household per year strongly reduced density and biomass. Low harvest intensity showed no adverse impact. Recommends rotational harvest. Density-based, not a matrix model. | verified-from-abstract |

---

## 2. Other harvest cases with matrix models

Ranked by how solid the harvest-treatment evidence is.

### 2.1 *Khaya senegalensis* (African mahogany; bark and foliage harvest; Benin): **strong**
**Gaoue OG, Ticktin T (2010).** Effects of harvest of nontimber forest products and ecological differences between sites on the demography of African mahogany. *Conservation Biology* 24(2): 605–614. DOI: [10.1111/j.1523-1739.2009.01345.x](https://doi.org/10.1111/j.1523-1739.2009.01345.x). **verified-from-fulltext**
- **Design:**
  - 12 populations: 6 in the Sudanian region (900–1100 mm rain) and 6 in the Sudano-Guinean region (1100–1300 mm).
  - Harvest level per population:
    - High harvest: more than 50% of trees pruned and less than 10% debarked.
    - Low harvest: less than 5% pruned and less than 5% debarked.
  - Censuses 2004–2006, giving two annual transitions.
  - 5 stages: seedling, sapling, juvenile, AD1 (20–40 cm dbh) and AD2 (≥40 cm dbh).
  - Population labels are in Table 1, p.607.
- **Deterministic λ, all populations pooled** (p.609):

  | Transition | λ | 95% CI |
  |---|---|---|
  | 2004–05 | **0.9587** | 0.9376–0.9757 |
  | 2005–06 | **1.0008** | 0.9840–1.0181 |

- **Extremes in 2004–05:**
  - Boukoussera (low harvest, Sudano-Guinean): **λ = 1.0419** (0.9906–1.1179).
  - Penelan: **λ = 0.8369** (0.6882–0.9166). This population was logged in 2005 and the authors excluded it from later analyses.
- **Stochastic λs** (pp.609–610, Fig. 1):

  | Group | λs | 95% CI |
  |---|---|---|
  | Overall | **0.9887** | 0.9865–0.9909 |
  | Sudanian region | 0.9823 | 0.9819–0.9826 |
  | Sudano-Guinean region | 1.0139 | 1.0127–1.0153 |
  | Sudano-Guinean, high harvest | **0.9913** | 0.9903–0.9923 |
  | Sudano-Guinean, low harvest | **1.0345** | 1.0338–1.0352 |
  | Sudanian, high harvest | **0.9659** | 0.9655–0.9664 |
  | Sudanian, low harvest | **0.9999** | 0.9998–1.0000 |

  High-harvest populations had λs significantly below 1 in both regions.
- **Effect sizes:**
  - Harvest effect: Δλs = 0.0148.
  - Region effect: Δλs = 0.0316, about twice the harvest effect.
- **Mechanisms:**
  - Stasis accounts for about 96% of total elasticity (Fig. 2).
  - LTRE: in the dry region, harvest lowered λ through reduced stasis of large stages. In the moist region, it lowered λ through reduced growth.
- **Recommendations:**
  - Reduce the proportion of trees harvested.
  - Promote harvester-owned plantations.
  - Create no-fire zones in gallery forests.
  - Even the Fulani "sustainable" pruning norm may not be sustainable: fewer than 20% of trees with less than 25% of the trunk debarked (p.613, citing Gaoue & Ticktin 2007).
- **Follow-up papers:**
  - Gaoue, Horvitz & Ticktin (2011) *Ecol Appl* 21: 1604–1616, [10.1890/10-0422.1](https://doi.org/10.1890/10-0422.1). Models harvest as a Markov chain. Populations "declined regardless of time between harvests of high intensity". In the moist region, λs fell toward ≈0.956 as harvest pressure decreased, driven by mean juvenile and adult survival. **verified-from-fulltext (abstract p.1604)**
  - Gaoue (2016) *J Appl Ecol* 53: 112–119, [10.1111/1365-2664.12553](https://doi.org/10.1111/1365-2664.12553). Transient dynamics. Mean matrices for 2004–2007 are openly downloadable (§4).
- **COMPADRE coverage:** 46 matrices from Gaoue & Ticktin 2010, plus 30 from Gaoue et al. 2013 *J Ecol* ([10.1111/1365-2745.12140](https://doi.org/10.1111/1365-2745.12140)).

### 2.2 *Panax quinquefolius* (American ginseng; root, i.e. whole-plant, harvest): **strong (simulation plus field)**
- **Nantel P, Gagnon D, Nault A (1996)** *Conserv Biol* 10: 608–621, [10.1046/j.1523-1739.1996.10020608.x](https://doi.org/10.1046/j.1523-1739.1996.10020608.x). **verified-from-abstract**
  - Stochastic PVA using four literature matrices from Quebec.
  - Mean λ declines with harvest rate *h* and return interval *t_r* as −0.54 h t_r^−0.90.
  - Harvesting plants with more than 2 leaves every 5 years at about **30%** brings λ below 1.
  - Extinction threshold is 30–90 plants. The **minimum viable population is about 170 plants**.
  - Only about a dozen Canadian populations exceed 170 plants.
  - Wild leek (*Allium tricoccum*): at 1–8% harvest, the probability that λ falls below 1 is under 5%.
- **Charron D, Gagnon D (1991)** *J Ecol* 79: 431–445, [10.2307/2260724](https://doi.org/10.2307/2260724). Base demography from protected and disturbed populations. COMPADRE has 8 matrices. Abstract not available, so the paper's own values are **unverified**.
- **Van der Voort ME, McGraw JB (2006)** *Biol Conserv* 130: 505–516, [10.1016/j.biocon.2006.01.010](https://doi.org/10.1016/j.biocon.2006.01.010).
  - Harvester-behaviour scenarios: non-compliant, compliant and steward.
  - Per secondary sources, only stewardship (delaying harvest, self-limiting intensity, planting seeds) reversed declining λ. Simple compliance with regulations was not enough (McGraw, Souther & Lubbers 2010). **secondary-source**
  - COMPADRE has 4 matrices for this paper (see §6).
- **Souther S, McGraw JB (2014)** *Ecol Appl* 24: 1463–1477, [10.1890/13-0653.1](https://doi.org/10.1890/13-0653.1). **verified-from-abstract**
  - 12 populations, 75 population-years.
  - Projected extinction risk at N = 140, with a quasi-extinction threshold of 20 plants:

    | Scenario | Extinction risk |
    |---|---|
    | Harvest + 1 °C warming over 70 years | **65%** |
    | Harvest alone | 8% |
    | Warming alone | 6% |

  - The combined effect is synergistic. Harvest and warming reduced growth from juvenile and small-adult stages to large adults.
- **Schmidt et al. 2011** (Table 1) used **Mooney (2007)**, with 18/6 populations, for *P. quinquefolius*. This species was one of 4 with a significant within-study effect of harvest on λ. **verified-from-fulltext**

### 2.3 *Garcinia lucida* (bark harvest; Cameroon): **moderate (abstract only)**
**Guedje NM, Zuidema PA, During H, Foahom B, Lejoly J (2007).** Tree bark as a non-timber forest product: the effect of bark collection on population structure and dynamics of *Garcinia lucida* Vesque. *For Ecol Manage* 240: 1–12. DOI: [10.1016/j.foreco.2006.09.029](https://doi.org/10.1016/j.foreco.2006.09.029). Citation verified via Crossref.

According to the ULB/RePEc abstract (read through a summarising fetch, so **secondary-source**):
- The study is a 2-year demographic study in South Cameroon.
- It models three harvest methods: partial debarking, ring-barking and felling.
- For all practices, "the asymptotic population growth rates (λ) were not significantly different from 1".
- The harvestable stock still declined. Under ring-barking or felling with annual harvest, it fell below about 4% of its initial size.
- Conclusion: commercial bark exploitation cannot be sustained.

COMPADRE has 5 mean matrices, covering unmanipulated, one-side debarking, ring-barking and felling before or after fruiting (§6).

### 2.4 *Prunus africana* (bark harvest; Cameroon): **weak (secondary only)**
- **Stewart KM (2009)** Effects of bark harvest and other human activity on populations of the African cherry (*Prunus africana*) on Mount Oku, Cameroon. *For Ecol Manage* 258: 1121–1128, [10.1016/j.foreco.2009.05.039](https://doi.org/10.1016/j.foreco.2009.05.039).
  - Per indexed-abstract snippets (**secondary-source**): 5 populations in the Kilum-Ijim forest, censused 1998–99 and 2007–08. A forest-wide bark harvest in 2005/06 shifted size structure toward smaller classes, and about half of reproductive trees died.
  - No λ is evident in the abstract.
- **Stewart KM (2001)** PhD dissertation, Florida International University. Per a search snippet, the combined-data λ = 0.9931 and the elasticity of large reproductive tree survival is 42.5%. **secondary-source, unverified**
- Schmidt et al. 2011 Table 1 lists "Stewart (2001)", with 4/4 populations over 2 years, harvested for bark only on target stages. They found that reduced survival, a high-elasticity rate, drove the λ reduction (p.819). **verified-from-fulltext**
- **No *Prunus africana* matrices exist in COMPADRE v6.26.3.0** (checked locally).

### 2.5 *Echinacea angustifolia* (root harvest; Great Plains, USA): **weak to moderate**
- **Hurlburt DP (1999)** Population ecology and economic botany of *Echinacea angustifolia*, a native prairie medicinal plant. PhD dissertation, University of Kansas.
  - Per Kindscher et al. 2008, p.142, Hurlburt "projected that populations can sustain a harvest of 4–5% of medium- to large-sized roots per year". Per p.141, plants can reach 18–44 years of age. **secondary-source** (secondary in the sense that Kindscher's full text was read, but the dissertation was not)
  - Schmidt et al. 2011 used Hurlburt (1999), with 4/4 populations over 2 years, and found harvest effects "varied greatly among sites and years".
- **Kindscher K, Price DM, Castle L (2008)** Resprouting of *Echinacea angustifolia* augments sustainability of wild medicinal plant populations. *Econ Bot* 62: 139–147, [10.1007/s12231-008-9016-9](https://doi.org/10.1007/s12231-008-9016-9). About **50% of harvested roots resprouted** within 2 years in Kansas and Montana. Shallower harvest led to more resprouting. **verified-from-fulltext** (abstract p.139)
- COMPADRE holds only unmanipulated *E. angustifolia* matrices (Dalgleish et al. 2010, 32 matrices). **There are no harvest-treatment matrices.**

### 2.6 Other medicinal or NTFP species with harvest matrix models (brief)
| Species (organ) | Source | Harvest evidence | Confidence |
|---|---|---|---|
| *Phyllanthus emblica*, *P. indofischeri* (amla; fruit) | Ticktin et al. 2012 *J Appl Ecol* 49: 774–784, [10.1111/j.1365-2664.2012.02156.x](https://doi.org/10.1111/j.1365-2664.2012.02156.x) | 10-year study. Fruit harvest had little effect on λs. Mistletoe and *Lantana* drive the decline. *P. emblica* fell to 16% of its original size where invasives were present. COMPADRE has 48 + 24 matrices covering harvest × mistletoe × *Lantana*. | verified-from-abstract |
| *Chamaedorea radicalis* (palm leaves) | Endress, Gorchov & Berry 2006 *For Ecol Manage* 234: 181–191, [10.1016/j.foreco.2006.07.020](https://doi.org/10.1016/j.foreco.2006.07.020); Endress et al. 2004 *Ecol Appl* (COMPADRE) | Schmidt et al. 2011: significant only at very high harvest levels. Low harvest did not reduce λ. | Schmidt: verified-from-fulltext. Endress values: unverified |
| *Chamaedorea elegans* (leaves) | Valverde et al. 2006 (COMPADRE: harvest 2× and 4× per year) | Schmidt et al. 2011: fertility was reduced but partly offset by survival. | verified-from-fulltext (Schmidt) |
| *Hydrastis canadensis* (goldenseal; rhizome; CITES App. II) | Christensen & Gorchov 2010 *Plant Ecol*, [10.1007/s11258-010-9749-2](https://doi.org/10.1007/s11258-010-9749-2) | **No harvest treatment.** λ > 1 for 1998–99 and below 1 for 1999–2000 (drought). | verified-from-abstract |
| *Saussurea laniceps*, *S. medusa* (whole plant) | Law (2007) dissertation; Law, Salick & Knight 2010 (COMPADRE, unmanipulated) | Schmidt et al. 2011 attribute the apparent positive harvest effects to temporal and spatial variation. | verified-from-fulltext (Schmidt) |
| *Syngonanthus nitens* (scapes) | Schmidt & Ticktin 2012 *Biol Conserv* (COMPADRE: 60 matrices, harvest timing × burning) | Not medicinal. A rich harvest-treatment design. | metadata only |
| *Pentadesma butyracea* (fruit) | Dryad h58kg (Biotropica, [10.1111/btp.12486](https://doi.org/10.1111/btp.12486)) | Fruit harvest reduces seedling density and raises clonal recruitment. | verified-from-abstract (Dryad metadata) |
| *Bertholletia excelsa* (fruit) | Dryad br360 ([10.1111/btp.12505](https://doi.org/10.1111/btp.12505)) | Sites at 39% and 81% harvest. Adult abundance projected stable or higher. | verified-from-abstract (Dryad metadata) |
| *Securidaca longepedunculata* (lethal harvest; medicinal; South Africa) | Figshare [10.6084/m9.figshare.33094676](https://doi.org/10.6084/m9.figshare.33094676.v1) | Bootstrap matrix PVA under lethal harvest. Paper not located. | dataset description only |
| *Aquilaria*, *Actaea*, *Arnica*, *Gentiana*, *Trillium*, *Paeonia*, *Euterpe*, *Astrocaryum*, *Pseudophoenix* | COMPADRE | Only unmanipulated or other-treatment matrices in COMPADRE v6.26.3.0. *Euterpe edulis* (Quitete-Portela et al. 2010) is labelled "Harvested", with no paired control in the same study. *Agave marmorata* has "cutting of flowering stalks". | local COMPADRE metadata |

---

## 3. Meta-analytic context

### 3.1 Schmidt IB, Mandle L, Ticktin T, Gaoue OG (2011)
*What do matrix population models reveal about the sustainability of non-timber forest product harvest?* *J Appl Ecol* 48: 815–826. DOI: [10.1111/j.1365-2664.2011.01999.x](https://doi.org/10.1111/j.1365-2664.2011.01999.x). **verified-from-fulltext**

- **Scope** (Summary and p.817):
  - 46 NTFP species from 20 families. 21 are palms, 12 trees, 12 herbs and 1 cycad. 73% are tropical.
  - 16 species had only simulated harvest. 10 lacked controls. 20 had both harvested and control populations, and 75% of those studies were published from 2005 onward.
  - 19 species were analysed, using 134 matrices.
  - 15 species had variance estimates for the meta-analysis.
- **Main result** (p.819, Fig. 1):
  - Harvest significantly reduced λ: Hedges' d = **−0.9427** (95% CI −1.6179 to −0.3877).
  - This is "equivalent to a λ of **1.04 in control** populations compared to **0.92 in harvested** populations".
  - Fail-safe N = 91.11, so the result is robust to publication bias.
- **Per-study power** (p.821): only 4 species showed a statistically significant within-study effect: *Chamaedorea radicalis*, *Khaya senegalensis*, *Nardostachys grandiflora* and *Panax quinquefolius*. For the other 11, the confidence intervals are too wide to tell. Most studies ran under 3 years with fewer than 5 populations.
- **By life form and part harvested** (Summary point 4; pp.819–821):
  - "Whole-plant harvest of herbs and bark harvest from trees were **not sustainable** largely because of decreases in survival."
  - "Palm leaf or fruit harvest and rattan stem harvest were **potentially sustainable**."
  - For *Echinacea*, *Nardostachys* and *Panax*, the vital rates most affected by harvest had both high elasticity and high negative LTRE contributions.
  - For the bark-harvested *Prunus africana* and *Khaya senegalensis*, survival had both high LTRE contributions and high elasticity.
- **Elasticity patterns** (p.819, Fig. 2):
  - Survival elasticity is highest in palms and trees and lowest in herbs. Growth elasticity is slightly higher in herbs.
  - Harvest reduced growth and fertility elasticities in palms, and growth elasticity in trees.
- **Recommendation:** use combined elasticity and LTRE analysis (Zuidema, de Kroon & Werger 2007) rather than λ alone. Studies are lacking for Africa, Asia and Europe, and for lianas, ferns, mosses and lichens.
- **No numeric "safe harvest limit"** is given across species.

### 3.2 Ticktin T (2004)
*The ecological implications of harvesting non-timber forest products.* *J Appl Ecol* 41: 11–21. DOI: [10.1111/j.1365-2664.2004.00859.x](https://doi.org/10.1111/j.1365-2664.2004.00859.x). **verified-from-abstract** (the full text returned 403)
- Reviewed **70 studies**.
- Tolerance to harvest varies with life history and the plant part harvested.
- Effects are mediated by environmental variation and by management practices.
- Many species need management beyond simple gathering to withstand heavy harvest.
- Ghimire 2008 (p.42, citing Ticktin 2004) notes that harvest of underground parts of most herbaceous perennials studied "has been reported to be unsustainable, even at low levels" (Nault & Gagnon 1993; Nantel et al. 1996; Rock et al. 2004). **verified-from-fulltext**, as a secondary statement inside Ghimire.
- The quantitative fraction of studies in Ticktin's sample showing unsustainable harvest is **unverified**, because I could not read the full text.

---

## 4. Open datasets beyond COMPADRE (details in `open_datasets.json`)

Method:
- I searched the Dryad v2 API, the Zenodo API and the Figshare API for NTFP, harvest, bark, root, defoliation, medicinal and species-specific terms.
- Most Dryad datasets have a Zenodo mirror. Mirror files were fetched anonymously with a ranged GET, which returned HTTP 206.
- **Direct Dryad file downloads now return HTTP 401** ("must have current bearer token") through the API, and 403 through the web file stream.

**Requested accessibility checks:**
- **TreeDivNet drought sapling survival**, [10.6084/m9.figshare.25359751](https://doi.org/10.6084/m9.figshare.25359751). CC BY 4.0, 14 files, including `data_surv_synthesis.csv` at 181.7 MB. **Downloadable without login**: a ranged GET returned CSV content. A HEAD request on the signed S3 redirect returns 403, but GET works.
- **European seed germination**, [10.5061/dryad.nk98sf86v](https://doi.org/10.5061/dryad.nk98sf86v). CC0, published 2025-12-11, 1,146 species and 18,596 tests, in one xlsx file. **Not downloadable anonymously by script**: the API returns 401, the web stream returns 403, and there is no Zenodo mirror. It probably works by manual browser download or with a free Dryad token.

**Harvest and regeneration datasets with raw data confirmed downloadable** (via Zenodo mirrors):
- Khaya mean matrices 2004–07 (dryad.mb1d0)
- Three dry-forest tree species, harvest vs no harvest, IPM data (dryad.mcvdnck27)
- *Pentadesma* fruit harvest (dryad.h58kg)
- *Chamaedorea ernesti-augustii* leaf removal (dryad.6j19m)
- *C. elegans* defoliation (dryad.q755t)
- *Euterpe precatoria* and *Mauritia flexuosa* (dryad.bn3kd)
- Brazil nut (dryad.br360)
- Lemongrass fire × harvest (dryad.m64s2)
- Drought × leaf harvest in two wild vegetables (dryad.z08kprrgv)
- Soil impacts of NTFP harvest (dryad.mp6d3)

**Medicinal species but not script-downloadable:**
- *Rauvolfia serpentina*, Nepal (dryad.vt4b8gv2q)
- *Prunus africana*, Rwanda (dryad.wdbrv165t)

**Medicinal species, download not tested:**
- *Securidaca longepedunculata* (figshare 33094676)

**Finding:** I found **no multi-species dataset of measured harvest experiments on medicinal plants** (multiple medicinal taxa with plant-part removal). Every candidate covers 1–3 species. GBIF holds occurrence data only, and no harvest-experiment datasets were identified there.

---

## 5. Governance context for *N. jatamansi*

| Item | Finding | Source | Confidence |
|---|---|---|---|
| CITES | Listed in **Appendix II** | Ghimire et al. 2008, p.42 ("listed in Appendix II of CITES"). Smith-Hall et al. 2023 analysed CITES trade data for **1997–2017**. A FairWild/TRAFFIC project is titled "CITES Appendix-II listed Jatamansi". | verified-from-fulltext (App. II status) |
| CITES listing year and meeting | Listed in 1997 at CoP10 (Harare) | CITES Plants Committee documents PC10 Doc 10.2.3 and PC22 Doc 21.2, seen only as search snippets because cites.org returned 403 or a bot challenge | **secondary-source** |
| CITES name and annotation | Listed as *N. grandiflora*. Per PC22 Doc 21.2, no synonyms are officially listed, which may distort trade data. PC10 suggested adding "rhizomes" to the roots annotation, but whether this was adopted is **unverified**. | search snippets | secondary-source / unverified |
| IUCN Red List | **Critically Endangered (CR), criterion A2cd.** Citation: Chauhan HK (2021) *Nardostachys jatamansi*. The IUCN Red List of Threatened Species 2021: e.T50126627A88304158. Gowthami et al. 2021 (*Genet Resour Crop Evol*, [10.1007/s10722-021-01199-0](https://doi.org/10.1007/s10722-021-01199-0), PMC8148398) list it as CR "as per IUCN (Source: IUCN 2020)". Smith-Hall 2023 calls it "critically endangered". | Smith-Hall et al. 2025 reference list (PMC12309637) for the citation; Gowthami 2021 full text. Criterion A2cd comes from a search snippet. | CR: verified-from-fulltext (secondary to IUCN). Assessment year 2015 vs 2021 and the criteria: **secondary-source**. iucnredlist.org returned 403. |
| Nepal: export of unprocessed rhizome | **Export of unprocessed jatamansi rhizome is formally prohibited.** Smith-Hall 2023 cites MFSC (1995) Forest Regulation. Despite this, central wholesalers exported an estimated **856,000 kg** of unprocessed air-dry rhizome in 2014–15. Smith-Hall 2025 lists "ban on export of unprocessed raw material [e.g., rhizomes of *N. jatamansi*]" as a transactional intervention. | Smith-Hall et al. 2023, Results (CITES paragraph). Smith-Hall et al. 2025, *Conserv Biol*, [10.1111/cobi.14442](https://doi.org/10.1111/cobi.14442), Fig. 1 caption | verified-from-fulltext (secondary to the regulation itself) |
| Nepal: harvest quota | Government annual quota of **878 t** for the districts where the species occurs (935 t including 3 non-occurrence districts). Estimated 2014–15 trade of 1,145 t was 30% above the quota. Trade exceeded quota in 15 districts. | Smith-Hall 2023, Table 1 and Results | verified-from-fulltext |
| Nepal: transport and permits | District-of-origin transport permits are required (Ministry of Forests and Environment 2019). Government records registered only part of the trade, so they "cannot be used to assess trade at any geographical scale". | Smith-Hall 2025; Smith-Hall 2023 | verified-from-fulltext |
| India | India has banned commercial collection of *N. jatamansi* rhizomes, but remains the main market for Nepali harvest | Smith-Hall 2025, citing Chauhan 2021 | verified-from-fulltext (secondary) |
| CITES trade data reliability | Exporters reported 73,500 kg per year, importers only 49 kg per year (1997–2017), and 99% came from Nepal. CITES data "cannot be used to assess actual trade levels". | Smith-Hall 2023 | verified-from-fulltext |
| Trade scale | National trade rose from **377 t (1997–98) to 1,145 t (2014–15)**. Nepal supplies 82% of annual global production (citing Olsen 2005). Harvesting households collect 106 ± 119 kg of air-dry rhizome per year. | Smith-Hall 2023 | verified-from-fulltext |
| Sustainable-yield scenarios | Stock of 141 kg air-dry rhizome per ha. Three scenarios: 10% harvest per 5-year rotation (Conservative, from Ghimire 2008 outcrop); 25% per 5 years (Common, from Ghimire 2008 meadow); 100% with replanting (Larsen 2005). Result: unsustainable harvest is concentrated in specific subnational areas. | Smith-Hall 2023, Methods step 3 | verified-from-fulltext |
| FairWild | Himalayan Bio Trade Ltd (Nepal) is FairWild-certified for jatamansi, kutki and sea buckthorn. Certified 2020, re-certified 2022 and 2025 (per its FairWild participant page; ANSAB reports the jatamansi and kutki come from Jumla district). Smith-Hall 2025: FairWild certification "is rare in Nepal". The TRAFFIC and ANSAB "Succeeding with CITES" Darwin project (DAR25018, 2018–2021) built jatamansi supply-chain and auditor capacity. | fairwild.org participant page (fetched); Smith-Hall 2025 | FairWild page: verified (official page fetched). Darwin project details: secondary-source |

---

## 6. Values for validating COMPADRE reproductions

COMPADRE v6.26.3.0 (local copy) contains **6 Nardostachys matrices** from Ghimire et al. 2008, MatrixIDs 244454–244459. All are **"Mean" composite** matrices covering 1999–2002 (6×6, stages Sd/J/A1–A4). Their dominant eigenvalues, which **I computed** from `compadre_matrices.npz` and which are **not literature values**, are:

| MatrixID | Population / treatment | λ computed from COMPADRE A | Paper's published comparator |
|---|---|---|---|
| 244454 | Meadow, unharvested, mean | 1.1522 | Annual range 1.12–1.17 (p.46). Consistent. |
| 244455 | Outcrop 0%, mean | 1.0277 | Annual range 1.01–1.04 (p.46). Consistent. |
| 244456 | Outcrop 10%, mean | 0.9582 | 1999–2000 annual value 0.928 |
| 244457 | Outcrop 25%, mean | 0.8912 | 1999–2000 annual value 0.838 |
| 244458 | Outcrop 50%, mean | 0.8305 | 1999–2000 annual value 0.779 |
| 244459 | Outcrop 75%, mean | 0.7369 | 1999–2000 annual value 0.637 |

**Interpretation:**
- The ranking and spacing match the paper.
- The COMPADRE mean-matrix λ values for harvested plots are higher than the 1999–2000 annual λ. That is expected, because the paper says λ rose in later years and the mean matrices weight all three years.
- **The exact published λ for the weighted mean matrices is in Table S1, which I could not access.** Do not claim exact reproduction against the 1999–2000 numbers.
- **The appropriate validation test:**
  - meadow λ inside [1.12, 1.17];
  - outcrop control inside [1.01, 1.04];
  - harvested λ monotonically decreasing with intensity and below the control;
  - all harvested λ below 1.
- **Missing from COMPADRE:** the commercially harvested meadow matrix and the per-year matrices.

**Other cross-checks** (COMPADRE λ computed by me vs published text):
- **Khaya, Boukoussera 2004–05:** the paper gives 1.0419. COMPADRE gives 1.0423 for MatrixID 247595 (labelled "Mean"), a near match, and 1.0878 for 247596 (labelled "Individual" 2004).
- **Khaya, Penelan 2004–05:** the paper gives 0.8369. The COMPADRE "Individual 2004" matrix (247605) gives 0.8533.
- **Conclusion:** COMPADRE's Khaya "Mean" and "Individual" labels may not map one-to-one onto the paper's annual matrices. Check MatrixComposite labels before validating.
- **Khaya pooled 2004–05:** the paper gives 0.9587. The COMPADRE pooled matrices give 0.9487 (high harvest), 0.968 (low harvest), 0.9651 (Sudanian) and 0.9801 (Sudano-Guinean). There is no all-population pooled matrix, so no direct comparator exists.
- **Independent Khaya check:** the openly downloadable mean matrices in dryad.mb1d0 / Zenodo 5001576 (Gaoue 2016) allow a check against COMPADRE.
- **Garcinia lucida:** COMPADRE λ ranges from 1.056 to 1.063 across all five treatments. This agrees with the abstract's "λ not significantly different from 1".
- ***Panax quinquefolius*, Van der Voort & McGraw 2006:** COMPADRE λ is 1.0389 (unmanipulated), 0.8523 (non-compliant), 0.9593 (compliant) and 1.0412 (steward). This qualitatively matches the secondary claim that only stewardship gives a non-declining population. The published numbers are **unverified**.

**Literature values to use as validation targets** (verified, see JSON):
- Nardostachys: annual λ by treatment; extinction probabilities 0.14 / 0.68 / 0.77 / 0.87; recovery times 5 / 17 / 33 / 6 years; harvest limits of 10% (outcrop) and 25% (meadow) with a rotation of at least 5 years.
- Khaya: stochastic λs by region × harvest.
- Schmidt 2011: pooled control vs harvested λ of 1.04 vs 0.92.

---

## 7. Open questions
1. **Ghimire 2008 Table S1 and Appendix S1:** these hold the matrix elements, the λ of the weighted mean matrices, the stochastic λ, and the exact harvest regime in the stochastic PVA (single vs repeated harvest). Wiley supplementary files were not reachable. Next step: download manually from the Wiley page, or email the authors.
2. **Commercially harvested meadow λ (1999–2000):** shown only in Fig. 2b. A figure digitisation would be an estimate, not a reported value.
3. **Ghimire et al. 2005 (Biol Conserv 124):** density, recruitment and regeneration-after-harvest values were not verified because the paper is closed access.
4. **Larsen 2005 replanting experiment:** regeneration rates were not verified. Only the secondary summary is available.
5. **CITES listing date (1997, CoP10) and current annotation:** need confirmation from cites.org or Species+, which blocked automated access.
6. **IUCN assessment:** the year (2015 vs 2021 publication) and the criteria (A2cd) need confirmation on iucnredlist.org, which returned 403.
7. **Prunus africana:** Stewart 2001 and 2009 λ values remain unverified. COMPADRE has no *P. africana* matrices.
8. **Echinacea:** Hurlburt 1999 matrices and the 4–5% harvest projection have not been read directly. COMPADRE has no harvest-treatment matrices for this species.
9. **Ticktin 2004:** quantitative breakdowns were not read because the full text was blocked.
10. **No multi-species open dataset of measured medicinal-plant harvest experiments was found.** The project should present COMPADRE treatment matrices, together with the single-species Dryad/Zenodo datasets above, as the empirical basis, and say clearly that this is a limitation.
