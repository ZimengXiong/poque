#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *RANKS = "23456789TJQKA";
static const char *SUITS = "cdhs";
static const char *HAND_NAMES[] = {
    "high card",
    "pair",
    "two pair",
    "three of a kind",
    "straight",
    "flush",
    "full house",
    "four of a kind",
    "straight flush",
};

static int parse_card(const char *text) {
    if (strlen(text) != 2) return -1;
    const char *rank = strchr(RANKS, text[0]);
    const char *suit = strchr(SUITS, text[1]);
    if (!rank || !suit) return -1;
    return (int)(suit - SUITS) * 13 + (int)(rank - RANKS);
}

static long pack(int category, int a, int b, int c, int d, int e) {
    return ((((((long)category * 15L + a) * 15L + b) * 15L + c) * 15L + d) * 15L + e);
}

static long rank5(const int cards[5]) {
    int ranks[5], suits[5], counts[13] = {0};
    for (int i = 0; i < 5; i++) {
        ranks[i] = cards[i] % 13;
        suits[i] = cards[i] / 13;
        counts[ranks[i]]++;
    }
    for (int i = 0; i < 4; i++) {
        for (int j = i + 1; j < 5; j++) {
            if (ranks[j] > ranks[i]) {
                int t = ranks[i]; ranks[i] = ranks[j]; ranks[j] = t;
            }
        }
    }

    int flush = 1;
    for (int i = 1; i < 5; i++) {
        if (suits[i] != suits[0]) flush = 0;
    }

    int present[13] = {0};
    for (int i = 0; i < 5; i++) present[ranks[i]] = 1;
    int straight = -1;
    for (int high = 12; high >= 4; high--) {
        if (present[high] && present[high - 1] && present[high - 2] && present[high - 3] && present[high - 4]) {
            straight = high;
            break;
        }
    }
    if (straight < 0 && present[12] && present[3] && present[2] && present[1] && present[0]) {
        straight = 3;
    }

    int four = -1, three = -1, pairs[2] = {-1, -1}, pair_count = 0;
    for (int r = 12; r >= 0; r--) {
        if (counts[r] == 4) four = r;
        else if (counts[r] == 3) three = r;
        else if (counts[r] == 2 && pair_count < 2) pairs[pair_count++] = r;
    }

    if (flush && straight >= 0) return pack(8, straight, 0, 0, 0, 0);
    if (four >= 0) {
        int kicker = -1;
        for (int r = 12; r >= 0; r--) if (counts[r] == 1) { kicker = r; break; }
        return pack(7, four, kicker, 0, 0, 0);
    }
    if (three >= 0 && pair_count > 0) return pack(6, three, pairs[0], 0, 0, 0);
    if (flush) return pack(5, ranks[0], ranks[1], ranks[2], ranks[3], ranks[4]);
    if (straight >= 0) return pack(4, straight, 0, 0, 0, 0);
    if (three >= 0) {
        int k[2], n = 0;
        for (int r = 12; r >= 0; r--) if (counts[r] == 1) k[n++] = r;
        return pack(3, three, k[0], k[1], 0, 0);
    }
    if (pair_count == 2) {
        int kicker = -1;
        for (int r = 12; r >= 0; r--) if (counts[r] == 1) { kicker = r; break; }
        return pack(2, pairs[0], pairs[1], kicker, 0, 0);
    }
    if (pair_count == 1) {
        int k[3], n = 0;
        for (int r = 12; r >= 0; r--) if (counts[r] == 1) k[n++] = r;
        return pack(1, pairs[0], k[0], k[1], k[2], 0);
    }
    return pack(0, ranks[0], ranks[1], ranks[2], ranks[3], ranks[4]);
}

static int category(long score) {
    long divisor = 15L * 15L * 15L * 15L * 15L;
    return (int)(score / divisor);
}

int main(int argc, char **argv) {
    if (argc != 8) {
        fprintf(stderr, "usage: %s <7 cards like As Kd ...>\n", argv[0]);
        return 2;
    }
    int cards[7];
    for (int i = 0; i < 7; i++) {
        cards[i] = parse_card(argv[i + 1]);
        if (cards[i] < 0) {
            fprintf(stderr, "invalid card: %s\n", argv[i + 1]);
            return 2;
        }
    }
    long best = -1;
    int combo[5];
    for (int a = 0; a < 3; a++)
    for (int b = a + 1; b < 4; b++)
    for (int c = b + 1; c < 5; c++)
    for (int d = c + 1; d < 6; d++)
    for (int e = d + 1; e < 7; e++) {
        combo[0] = cards[a]; combo[1] = cards[b]; combo[2] = cards[c]; combo[3] = cards[d]; combo[4] = cards[e];
        long score = rank5(combo);
        if (score > best) best = score;
    }
    printf("%ld\t%s\n", best, HAND_NAMES[category(best)]);
    return 0;
}
