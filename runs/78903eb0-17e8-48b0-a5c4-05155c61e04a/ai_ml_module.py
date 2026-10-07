import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB


# Seed training data
_SEED_TEXTS = [
    "buy groceries at the supermarket",
    "dinner at a nice restaurant",
    "gasoline for the car",
    "bus ticket for the weekend",
    "movie night at the theater",
    "internet bill paid",
    "electricity bill last month",
    "shopping online for clothes",
    "buy a new phone",
    "coffee at the cafe",
    "train ticket to new york",
    "ticket to the concert",
    "paying rent for the apartment",
    "gym membership renewal",
    "vacuum cleaner purchase",
    "pizza delivery order",
    "train to work",
    "movie streaming subscription",
    "buying office supplies",
    "paying utility bills"
]

_SEED_LABELS = [
    "Shopping",  # groceries
    "Food",      # dinner
    "Transport", # gasoline
    "Transport", # bus ticket
    "Entertainment", # movie night
    "Utilities",      # internet bill
    "Utilities",      # electricity
    "Shopping",       # online clothes
    "Shopping",       # new phone
    "Food",           # coffee
    "Transport",      # train ticket
    "Entertainment",  # concert
    "Utilities",      # rent
    "Utilities",      # gym membership
    "Shopping",       # vacuum cleaner
    "Food",           # pizza
    "Transport",      # train to work
    "Entertainment",  # movie streaming
    "Shopping",       # office supplies
    "Utilities"       # utility bills
]

_CATEGORIES = ["Food", "Transport", "Entertainment", "Utilities", "Shopping", "Other"]


class SpendSenseClassifier:
    def __init__(self):
        self.vectorizer = CountVectorizer(
            lowercase=True,
            token_pattern=r"\b\w+\b"
        )
        # Fit vectorizer on seed data
        self.vectorizer.fit(_SEED_TEXTS)

        # MultinomialNB supports partial_fit
        self.model = MultinomialNB()
        X_train = self.vectorizer.transform(_SEED_TEXTS)
        self.model.partial_fit(X_train, _SEED_LABELS, classes=_CATEGORIES)

    def categorize(self, text: str) -> str:
        """Predict category for a single text. Returns 'Other' if confidence < 0.4."""
        X = self.vectorizer.transform([text])
        probs = self.model.predict_proba(X)[0]
        idx = np.argmax(probs)
        confidence = probs[idx]
        pred = self.model.classes_[idx]
        return pred if confidence >= 0.4 else "Other"

    def partial_fit(self, texts: list[str], labels: list[str]) -> None:
        """
        Update the model with new labeled examples.
        Parameters
        ----------
        texts : list of str
            New sample texts.
        labels : list of str
            Corresponding labels.
        """
        X = self.vectorizer.transform(texts)
        # Ensure classes are known
        self.model.partial_fit(X, labels)

    def add_examples(self, texts: list[str], labels: list[str]) -> None:
        """
        Convenience method to add new examples and retrain the vectorizer.
        """
        # Update dataset
        all_texts = list(self.vectorizer.get_feature_names_out())  # not used; just placeholder
        # Fit vectorizer again on all data (small dataset, acceptable)
        combined_texts = _SEED_TEXTS + texts
        self.vectorizer.fit(combined_texts)
        X = self.vectorizer.transform(combined_texts)
        self.model.partial_fit(X, _SEED_LABELS + labels)


# Create a global instance that is ready at import time
_classifier = SpendSenseClassifier()


def categorize(text: str) -> str:
    """Top‑level helper that uses the global classifier."""
    return _classifier.categorize(text)


def partial_fit(texts: list[str], labels: list[str]) -> None:
    """Top‑level helper to update the global model."""
    _classifier.partial_fit(texts, labels)