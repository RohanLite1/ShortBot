from ai_engine import classify_relevance


def classify_short(user_request, title):
    return classify_relevance(user_request, title)


if __name__ == "__main__":
    # Test
    user_request = "Find funny Young Sheldon Shorts about Sheldon and Missy"

    titles = [
        "Sheldon and Missy have the funniest fight 😂 | Young Sheldon",
        "Missy and Sheldon meet Mandy for the first time 😂 | Young Sheldon",
        "How to Make Perfect Chocolate Cake",
    ]

    for title in titles:
        result = classify_short(user_request, title)
        print("TITLE:", title)
        print("MATCH:", result)
        print("-" * 50)