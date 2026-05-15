from tools.deal_history import (
    list_recent_saved_deals,
    find_saved_deals_by_verdict,
    get_best_saved_deal,
)


def main():
    print("\nRecent saved deals:")
    print(list_recent_saved_deals(limit=5))

    print("\nSaved WALK AWAY deals:")
    print(find_saved_deals_by_verdict("WALK AWAY", limit=5))

    print("\nBest saved deal by cash-on-cash return:")
    print(get_best_saved_deal("cash_on_cash_return"))


if __name__ == "__main__":
    main()
