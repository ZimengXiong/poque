import random
from enum import Enum


class Action(Enum):
    FOLD = 1
    CHECK = 2
    CALL = 3
    RAISE = 4
    SMALL_BLIND = 5
    BIG_BLIND = 6


stages = [2,5,6,7]
class Stage(Enum):
    PREFLOP = 2
    FLOP = 5
    TURN = 6
    RIVER = 7


class Game:
    def __init__(self, n):
        # 7 cards player 1, 7 cards player 2, ..., 7 cards player n
        self.n = n
        self.dealerIdx = 0
        self.playerMoney = [10] * self.n
        self.newRound()

    def nextStage(self):
        match self.stage:
            case Stage.PREFLOP:
                self.stage = Stage.FLOP
            case Stage.FLOP:
                self.stage = Stage.TURN
            case Stage.TURN:
                self.stage = Stage.RIVER
            case Stage.RIVER:
                self.newRound()

    def newRound(self):
        all = random.sample(range(1, 53), self.n * 2 + 5)
        self.stack = [all[i * 2 : i * 2 + 2] + all[-5:] for i in range(self.n)]
        self.dealerIdx = (self.dealerIdx + 1) % self.n
        self.pot = 0
        self.stage = Stage.PREFLOP
        self.stack = [0] * (self.n * 7)
        self.playerMoney = [abs(x) for x in self.playerMoney]

    def getPlayer(self, playerIdx):
        return {
            "hand": self.stack[playerIdx * 2 : playerIdx * 2 + self.stage],
            "playerMoney": abs(self.playerMoney[playerIdx]),
        }

    def action(self, playerIdx, action, amount=0):
        match action:
            case Action.FOLD:
                self.playerMoney[playerIdx] *= -1
            case Action.CALL:
                if (self.playerMoney[playerIdx] - self.bet_amount) < 0:
                    print("Not able to call")
                    return False
                self.playerMoney[playerIdx] -= self.bet_amount
                self.pot += self.bet_amount
            case Action.RAISE | Action.BIG_BLIND | Action.SMALL_BLIND:
                if (
                    self.playerMoney[playerIdx] - amount
                ) < 0 or amount < self.bet_amount:
                    print("Not able to raise")
                    return False
                self.playerMoney[playerIdx] -= amount
                self.pot += amount
                self.bet_amount = amount
        return True

    def nextStage(self):
        self.stage = self.stage.next
