def convert(cards):
    primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]
    suits = [0x8000, 0x4000, 0x2000, 0x1000]  # clubs, diamonds, hearts, spades

    pokerlibCards = []
    for card in cards:
        rankIdx = (card - 1) % 13
        suitIdx = (card - 1) // 13
        rank = rankIdx + 2

        prime = primes[rankIdx]
        suit = suits[suitIdx]
        rankBits = 1 << (16 + rankIdx)

        pokerlibCards.append(prime | (rank << 8) | suit | rankBits)

    return pokerlibCards


def rank7(cards):
    pokerlibCards = convert(cards)

    def findFast(product):
        product = (product + 0xE91AAA35) & 0xFFFFFFFF
        product ^= product >> 16
        product = (product + (product << 8)) & 0xFFFFFFFF
        product ^= product >> 4
        b = (product >> 8) & 0x1FF
        a = ((product + (product << 2)) & 0xFFFFFFFF) >> 19
        return a ^ hashAdjust[b]

    def rank5(c1, c2, c3, c4, c5):
        q = (c1 | c2 | c3 | c4 | c5) >> 16

        if c1 & c2 & c3 & c4 & c5 & 0xF000:
            return flushes[q]

        straightOrHighCard = unique5[q]
        if straightOrHighCard:
            return straightOrHighCard

        product = (c1 & 0xFF) * (c2 & 0xFF) * (c3 & 0xFF) * (c4 & 0xFF) * (c5 & 0xFF)
        return hashValues[findFast(product)]

    best = 9999
    return best
