from game import Game, Action

N = int(input("How many players?"))
curGame = Game(N)

for i in range(N):
    print("Player " + str(i + 1) + ": " + str(curGame.getPlayer(i)))
    print("The current bet is " + str(curGame.bet_amount))

    if i == curGame.dealerIdx:
        print("You are the dealer.")
    elif i == (curGame.dealerIdx + 1) % N:
        print("You are the small blind.")
        if curGame.getPlayer(i)["playerMoney"] < 1:
            print("You do not have enough money to continue the game")
            continue
        curGame.action(i, Action.SMALL_BLIND, 1)
    elif i == (curGame.dealerIdx + 2) % N:
        print("You are the big blind.")
        if curGame.getPlayer(i)["playerMoney"] < 2:
            print("You do not have enough money to continue the game")
            continue
        curGame.action(i, Action.BIG_BLIND, 2)
    else:
        valid = False
        while not valid:
            action = input("What would you like to do? (F)old, (C)all, (R)aise")
            if action == "F":
                print("You have folded.")
                valid = curGame.action(i, Action.FOLD)
            elif action == "C":
                valid = curGame.action(i, Action.CALL)
                if valid: print("You have called the bet.")
            elif action == "R":
                amount = input("How much would you like to raise?")
                valid = curGame.action(i, Action.RAISE, int(amount))
                if valid: print("You have raised the bet.")
            else:
                print("Invalid action")

    stage = curGame.nextStage()

