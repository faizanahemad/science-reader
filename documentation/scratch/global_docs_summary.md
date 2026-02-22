# Global Documents Summary

Summary of the 3 PDFs stored in `storage/global_docs/`. All originate from the Amazon Ads Trust (AT) Science team, prepared around February 2026, describing the next-generation content moderation strategy.

---

## 1. larger-context.pdf

**"Ads Trust Content Moderation: Comprehensive Reference"** — 30 pages

The master reference document for Amazon's entire ad moderation infrastructure.

### Scope

Covers the full ML pipeline processing ~23 million ads/day across 40+ languages and 21+ marketplaces. The system uses a three-service architecture: Video Preprocessor, LLM Feature Generator, and LLM Classifier (~800 labels across 40 root policy nodes, 15 currently covered).

### Moderation Funnel (by complexity)

1. **Ingestion/Orchestration** — MARS ecosystem, Model Orchestrator (new) vs MLSG (legacy), AWS Step Functions, DynamoDB.
2. **Annotation/Enrichment** — Image Annotation Service (ConvNeXt V2), Content Annotation Rules/Service (CARRS/CAS).
3. **Advertiser Trust (TAP)** — Trust scoring: TAP 1.0 (heuristic) evolved to TAP 2.0 (ML: Random Forest, XGBoost, LightGBM, Extra-Trees). 20% audit sampling, 4-hour profile updates.
4. **Content Matching (CMS)** — ElasticSearch + embeddings + HNSW similarity matching. 25.62% volume reduction at 97.88% precision, ~$733K/year savings.
5. **Smart Moderation** — XLM-RoBERTa + ConvNeXt V2 multi-modal fusion. Risk buckets H0-H3. 26% automation at 98.6% precision, ~$279K/year savings.
6. **Cascaded Architecture (TIER-1)** — 39-59 specialized policy models. 50-80% traffic reduction, 78% model invocation reduction, ~$147-162K/year savings.
7. **Decision Maker (DM)** — XGBoost ensemble (DMv1-DMv3 + Simplified DM, ~50x smaller). Outputs APPROVED, UNDECIDED, or risk scores.
8. **Human Review (Sherlock)** — UI for UNDECIDED ads, with PriMo prioritization.

### Reactive and Quality Systems

- **CLAD** — Self-learning re-moderation of top 1-10% impression ads. 1-1.5M ads/week, ~$226K/year savings, +805% defect detection gain (Belgium).
- **ReACT** — Rapid-response tool (Dec 2024), removes ~4,700 defective ASINs/month.
- **Oculus** — Visual similarity defect discovery, 98.86% increase in defective ad coverage.
- **Quality Measurement** — DAV-1k via PPSWOR sampling (~20K ads weekly), Smart Audit (3-10%), Signal Audit, ICAP remediation.

### Policy Framework

~700 categories in L1-L6 hierarchy. Policy Applicability Rules (PARs), Eurus Decision Engine, ~262 entities in the Policy Knowledge Graph.

### SSDVA ML Architecture

Cascaded pipeline with VLLM backbone: Metadata Extraction -> LLM Featurization -> Unsupervised Clustering -> Adapter Processing -> Conditional Refinement -> Label Validation/Aggregation. Training data challenge: only ~10K/week vs millions for SP; only 12 of 200+ Healthcare labels had 100+ samples over 7 months. Uses BATMAN labels (AT Labels V2.0). Annual cost: ~$606K.

### APAA (Ad-Program Agnostic Architecture)

Standardizes into 8 asset types. "Index Once, Process Later" philosophy. Migration: March 2026 (SB tech-ready) through December 2026 (SP/SP Books kickoff).

### Unified Content Moderation Proposal (Section 8)

The strategic vision: transition from program-specific supervised learning to unified policy-agnostic moderation. Policies become explicit inputs (not encoded in model weights). Multi-tier architecture (Tier 0-4+), teacher-student distillation loop, auto-reject capability, entity taxonomy approach, phased execution plan. 10 tenets defined.

### Revenue Stakes

- $60M Pharma opportunity took 4 months to deliver
- $246M incremental first-year revenue for RMG, pharma, alcohol
- $40B+ self-service DSP opportunity blocked by lack of real-time enforcement
- Total annual savings from existing optimizations: >$1M (CMS + Smart Mod + Cascaded + CLAD)

### Automation Targets (end of 2026: 95% across all programs)

| Program | Current | 2026 Target | 2027 Target |
|---------|---------|-------------|-------------|
| SP | 99.88% | steady | steady |
| SB | 38% | 89% | 95% |
| SSDVA | 47% | 55% | 95% |
| SPV | 0% | 40% | 95% |

### Key Tech Stack

ConvNeXt V2, XLM-RoBERTa, XGBoost, vLLM, LoRA/PEFT adapters, CLIP, DINOv2, SmolVLM, FlanT5-XL, Claude-3, FAISS, all-mpnet-base-v2, HNSW.

### Key Systems

MARS, Sherlock, Lestrade, Houston, Polaris, Eurus, MLSG, Oculus, CLAD, ReACT, PriMo, CARRS, CAS, IAS, ISA, TAP, CMS, CCS, ExpHub.

---

## 2. AI use in Policy Revolution.pdf

**"AI Use in Policy Revolution"** — 8 pages

A focused document on how AI tools are transforming advertising policy development, validation, and enforcement. Contains multiple contributor drafts (Faizan Ahemad, Priyanka, Anurag, Rashmi).

### Two Core Initiatives

1. **ML-HITL (Machine Labeling with Human-In-The-Loop)** — Machines generated 57% of labels for SS-DVA in 2025. Coverage: 67.62% image, 48.65% video, 87.63% ASIN. Processes ~0.5M DSP ad assets/month. Launched August 2025. 2026 target: 55% full automation (no human touchpoints).

2. **Policy Revolution (2025/2026)** — Three AI tools:
   - **Policy Label Definition Validator** — LLM-based tool that flags ambiguous language ("reasonable," "prominent," "excessive"), detects definition collisions, identifies missing guidance, checks scope drift, validates inclusion/exclusion criteria across modalities. Produced 14 detailed analysis reports; 9 broad policy inputs accepted; 3 content policy risks acknowledged.
   - **Synthetic Data Generation** — Critical for sensitive categories (nudity, violence, offensive, privacy invasion) where 100% of training/testing data is synthetic. Audit dataset: 461 total samples (329 synthetic / 131 real).
   - **LLM-as-a-Judge** — Takes 3 inputs (rubric, content, context), outputs structured machine-readable judgments with calibrated scores and explanations.

### Key Result

Cross-annotator agreement improved from 85% to 95%+ for tested policies — a direct result of AI-assisted policy rewriting. This creates a virtuous cycle: precise policies -> consistent labeling -> better automation -> improved training data -> better models.

### Modalities Covered

Text, image, video, audio, image+text, ASIN. Audio, Text, HTML5 on the 2026 roadmap.

### Note

Sponsored programs run at ~100x higher volume than DSP, amplifying both the ROI of good labels and the damage of bad ones.

---

## 3. Enabling an unbridled ads growth with Day-1 Moderation.pdf

**"Enabling an Unbridled Ads Growth with Day-1 Moderation V2"** — 14 pages

The strategic proposal document making the business case for the Day-1 moderation system. Contributors: Hila Hashemi, Faizan Ahemad, Imroj Qamar, Rohan Paul.

### Core Problem

Content moderation has become a "slowing agent in ads growth." The current system was built incrementally for high-volume programs (SP at >99% automation) but cannot scale to new programs, policies, and markets. The combinatorial explosion across 4 dimensions (Ad Program x Marketplace x Asset Type x Policy) makes per-program supervised learning unsustainable.

### Fundamental Shift

From "policies encoded in model weights" (supervised learning) to "policies as explicit inputs" (VLMs + Policy Knowledge Base + RAG). This enables Day-1 readiness for any new program, vertical, or policy change without retraining.

### Day-1 Moderation Architecture (7 layers)

1. **Policy Layer** — Policy Knowledge Base mapping policies into regularized taxonomy using world knowledge + Amazon narratives. Downstream components immune to policy changes.
2. **Filtration Upgrades** — Enhanced TAP and cache-based decisions with new high-performance embeddings.
3. **Day-1 Models** — Open-world LLMs for novelties. Two-staged: high-recall RAG layer + high-precision agentic flow. Not cost-optimized; volume gradually channels to Day-n.
4. **Day-n Models** — Existing backbone for mature, high-volume programs. Automatic alternator between Day-1 and Day-n based on performance criteria.
5. **LLM Judge** — Pre-human layer; hypothesis that sufficiently large panel size achieves human-par performance with more consistency.
6. **HITL** — Human moderators remain for final decisioning, auditing, and correction.
7. **Reactive Moderation** — Increased investment needed as generalization causes more defect leakage.

### Expected Day-1 POC Results

30% automation with 95% precision and 85% recall.

### 7 Tenets

Training-independent Day-1 automation, automation as default, bounded risk, decouple policy from architecture, costs improve with scale, learn from every decision, auditable/explainable decisions.

### KPI Improvements (SS-DVA targets)

| KPI | Current State | Target State |
|-----|--------------|--------------|
| Time to market | 10 months | 1 month |
| New label coverage | 5 weeks | 3 days |
| Marketplace expansion | 3 months | 1 month |
| Day-1 performance | N/A | 95P / 85R |

### Phased Timeline

- Q1 2026: POCs for Day-1 + ML infra themes
- Q2 2026: Production path for DVA labeling
- Q3 2026: Initial system launch with off-the-shelf VLMs
- Q4 2026: PKB + High-Recall Router deployed
- Q1-Q2 2027: Cross-modal embeddings, fine-tuned VLMs, agentic capabilities, ML infra
- 2027: Delivery of Day-1 system + >95% automation

### Ultimate Vision

Miniaturize Day-1 moderation components to low-latency/low-cost and move upstream for pre-moderation during campaign creation time (self-service DSP).

### Challenges

- **Cost**: Large enterprise models costly at scale; mitigated by upstream filtering, policy simplification, fine-tuned internal models, expected VLM cost drops.
- **Migration Risk**: SP at 99.8% automation risks initial performance drops during transition.
- **Resource Constraints**: Hiring freeze and layoffs constrain bandwidth.
- **Complexity**: Covering all programs/verticals/edge cases while maintaining simplicity requires org-wide effort.

---

## Cross-Document Relationships

| Document | Role | Focus |
|----------|------|-------|
| larger-context.pdf | Master technical reference | Full system architecture, all components, metrics, unified proposal |
| AI use in Policy Revolution.pdf | Focused companion | AI tools for policy rewriting, validation, and machine labeling |
| Day-1 Moderation.pdf | Strategic proposal | Business case, revenue stakes, execution roadmap, architectural vision |

All three share identical automation target tables, the same tenets, and the same KPI frameworks — confirming they are a coordinated body of work driving Amazon Ads Trust's next-generation content moderation strategy.
