from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel
import csv
from pathlib import Path

# ── 1. Your Knowledge Base ──
class DrugInteractionKB:
    def __init__(self, ddi_csv=None, food_csv=None):
        self.ddi = {}
        self.food = {}
        if ddi_csv and Path(ddi_csv).exists():
            self._load_ddi(ddi_csv)
        if food_csv and Path(food_csv).exists():
            self._load_food(food_csv)
        if not self.ddi:
            self._seed_demo_data()

    @staticmethod
    def _norm(s): return str(s).strip().lower()
    @staticmethod
    def _key(a, b):
        x, y = sorted([a, b])
        return x, y

    def _load_ddi(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                a = self._norm(row.get("drug_1") or row.get("drug1") or "")
                b = self._norm(row.get("drug_2") or row.get("drug2") or "")
                if not a or not b: continue
                sev = (row.get("severity") or "unknown").lower()
                self.ddi[self._key(a, b)] = {
                    "drug1": a, "drug2": b, "severity": sev,
                    "description": row.get("description") or "",
                    "recommendation": row.get("recommendation") or self._default_rec(sev),
                    "source": row.get("source", "FDA DailyMed"),
                }

    def _load_food(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                food = self._norm(row.get("food") or "")
                drug = self._norm(row.get("drug") or "")
                if not food or not drug: continue
                self.food[(food, drug)] = {
                    "food": food, "drug": drug,
                    "severity": (row.get("severity") or "moderate").lower(),
                    "description": row.get("description") or f"{food} interacts with {drug}",
                    "recommendation": row.get("recommendation") or f"Avoid {food} while taking {drug}",
                }

    @staticmethod
    def _default_rec(sev):
        return {
            "major":    "Do not take together without consulting your doctor.",
            "severe":   "Do not take together without consulting your doctor.",
            "moderate": "Use caution. Monitor for side effects.",
            "minor":    "Monitor for any unusual symptoms.",
        }.get(sev, "Consult your doctor about this combination.")

    def _seed_demo_data(self):
        demo = [
            ("warfarin",  "aspirin",     "severe",   "Increased bleeding risk."),
            ("warfarin",  "ibuprofen",   "severe",   "NSAIDs increase bleeding risk with warfarin."),
            ("aspirin",   "ibuprofen",   "moderate", "Both are NSAIDs; combined GI risk."),
            ("metformin", "alcohol",     "moderate", "Risk of lactic acidosis."),
            ("lisinopril","ibuprofen",   "moderate", "NSAIDs reduce antihypertensive effect."),
            ("simvastatin","amiodarone", "severe",   "Risk of rhabdomyolysis."),
            ("digoxin",   "amiodarone",  "severe",   "Amiodarone raises digoxin levels."),
            ("clopidogrel","omeprazole", "moderate", "Omeprazole reduces clopidogrel efficacy."),
        ]
        for a, b, sev, desc in demo:
            self.ddi[self._key(a, b)] = {
                "drug1": a, "drug2": b, "severity": sev,
                "description": desc,
                "recommendation": self._default_rec(sev),
                "source": "Demo seed",
            }
        self.food[("grapefruit", "simvastatin")] = {
            "food": "grapefruit", "drug": "simvastatin", "severity": "major",
            "description": "Grapefruit raises simvastatin blood levels.",
            "recommendation": "Avoid grapefruit juice while on simvastatin.",
        }
        self.food[("alcohol", "metformin")] = {
            "food": "alcohol", "drug": "metformin", "severity": "moderate",
            "description": "Alcohol + metformin increases lactic acidosis risk.",
            "recommendation": "Limit alcohol intake.",
        }

    def check_pairs(self, drugs):
        results, seen = [], set()
        for i, d1 in enumerate(drugs):
            for d2 in drugs[i+1:]:
                k = self._key(self._norm(d1), self._norm(d2))
                if k in seen: continue
                seen.add(k)
                if k in self.ddi:
                    results.append(self.ddi[k])
        order = {"severe": 0, "major": 1, "moderate": 2, "minor": 3, "unknown": 4}
        results.sort(key=lambda r: order.get(r["severity"], 4))
        return results

    def check_food(self, foods, drugs):
        out = []
        for food in foods:
            for drug in drugs:
                k = (self._norm(food), self._norm(drug))
                if k in self.food:
                    out.append(self.food[k])
        return out

    def stats(self):
        return {"ddi_pairs": len(self.ddi), "food_pairs": len(self.food)}

# ── 2. FastAPI App ──
app = FastAPI(title="MediBuddy Interaction API", version="1.0")

# 🔥 THIS IS THE MOST IMPORTANT PART FOR YOUR FLUTTER WEB APP
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fire-setup-1fc97.web.app",      # Your Firebase Hosting domain
        "https://fire-setup-1fc97.firebaseapp.com",
        "http://localhost:3000",                 # For local testing
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KB = DrugInteractionKB(ddi_csv=None, food_csv=None)

class InteractionRequest(BaseModel):
    drugs: list[str]
    foods: list[str] = []
    allergies: list[str] = []

@app.get("/health")
def health():
    return {"status": "ok", **KB.stats()}

@app.post("/interactions")
def check(req: InteractionRequest):
    if len(req.drugs) < 2:
        raise HTTPException(400, "Need at least 2 drugs to check interactions")

    drug_hits  = KB.check_pairs(req.drugs)
    food_hits  = KB.check_food(req.foods, req.drugs) if req.foods else []

    allergy_hits = []
    for allergy in req.allergies:
        for d in req.drugs:
            if allergy.lower() in d.lower():
                allergy_hits.append({
                    "drug": d, "allergy": allergy, "severity": "severe",
                    "description": f"Patient is allergic to {allergy}",
                    "recommendation": "Do not administer. Consult prescriber.",
                })

    severe = sum(1 for i in drug_hits if i["severity"] in ("severe", "major"))
    return {
        "drug_interactions": drug_hits,
        "food_interactions": food_hits,
        "allergy_warnings":  allergy_hits,
        "summary": {
            "total": len(drug_hits) + len(food_hits) + len(allergy_hits),
            "severe_count": severe,
            "has_severe": severe > 0,
        },
    }
