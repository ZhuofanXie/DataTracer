from collections import Counter
from itertools import permutations

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import RandomizedSearchCV
from tqdm import tqdm

from .base import ForeignKeySolver


class StandardForeignKeySolver(ForeignKeySolver):

    def __init__(self):
        self.model = RandomizedSearchCV(RandomForestClassifier(), {
            "n_estimators": [100, 250],
            "criterion": ["gini", "entropy"],
            "max_depth": [None, 1, 2, 3],
            "class_weight": ["balanced"]
        })

    def fit(self, list_of_databases):
        X, y = [], []
        for metadata, tables in tqdm(list_of_databases, "extracting features"):
            fks = metadata.get_foreign_keys()
            fks = set([(fk["table"], fk["field"], fk["ref_table"], fk["ref_field"]) for fk in fks])

            for t1, t2 in permutations(tables.keys(), r=2):
                for c1 in tables[t1].columns:
                    for c2 in tables[t2].columns:
                        if tables[t1][c1].dtype.kind != tables[t2][c2].dtype.kind:
                            continue
                        if len(tables[t1][c1]) == 0 or len(tables[t2][c2]) == 0:
                            print(tables.keys())
                            raise RuntimeError("Found empty table!")
                        X.append(self._feature_vector(tables[t2][c2], tables[t1][c1]))
                        y.append(1.0 if (t1, c1, t2, c2) in fks else 0.0)
        self.model.fit(X, y)

    def solve(self, tables, primary_keys=None):
        X, foreign_keys = [], []
        for t1, t2 in permutations(tables.keys(), r=2):
            for c1 in tables[t1].columns:
                for c2 in tables[t2].columns:
                    if tables[t1][c1].dtype.kind != tables[t2][c2].dtype.kind:
                        continue
                    X.append(self._feature_vector(tables[t2][c2], tables[t1][c1]))
                    foreign_keys.append((t1, c1, t2, c2))
        if not foreign_keys:
            return []
        scores = self.model.predict(X)

        best_foreign_keys = []
        for score, (t1, c1, t2, c2) in sorted(zip(scores, foreign_keys), reverse=True):
            best_foreign_keys.append({
                "table": t1,
                "field": c1,
                "ref_table": t2,
                "ref_field": c2,
                "score": score,
                "features": self._feature_vector(tables[t2][c2], tables[t1][c1])
            })
        return best_foreign_keys

    def _feature_vector(self, parent_col, child_col):
        parent_set, child_set = set(parent_col), set(child_col)
        len_intersect = len(parent_set.intersection(child_set))
        return [
            len_intersect / (len(child_set) + 1e-5),
            len_intersect / (len(parent_set) + 1e-5),
            len_intersect / (max(len(child_set), len(parent_set)) + 1e-5),
            1.0 if parent_col.name == child_col.name else 0.0,
            self._diff(parent_col.name, child_col.name),
            1.0 if child_set.issubset(parent_set) else 0.0,
            1.0 if parent_set.issubset(child_set) else 0.0,
            len(parent_set) / (len(parent_col) + 1e-5),
            1.0 if "key" in parent_col.name else 0.0,
            1.0 if "id" in parent_col.name else 0.0,
            1.0 if "_key" in parent_col.name else 0.0,
            1.0 if "_id" in parent_col.name else 0.0,
            1.0 if parent_col.dtype == "int64" else 0.0,
            1.0 if parent_col.dtype == "object" else 0.0,
            len(child_set) / (len(child_col) + 1e-5),
            1.0 if "key" in child_col.name else 0.0,
            1.0 if "id" in child_col.name else 0.0,
            1.0 if "_key" in child_col.name else 0.0,
            1.0 if "_id" in child_col.name else 0.0,
            1.0 if child_col.dtype == "int64" else 0.0,
            1.0 if child_col.dtype == "object" else 0.0,
        ]

    def _diff(self, a, b):
        diff = 0
        a, b = Counter(a), Counter(b)
        for k in set(a.keys()).union(set(b.keys())):
            diff += abs(a[k] - b[k])
        return diff
