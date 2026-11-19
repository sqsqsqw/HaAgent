from .chat import ChatAgent

def start():

    chatAgent = ChatAgent()

    while True:
        user_input = input("Human:")

        oper = user_input.split(" ")[0]
        if oper == "/quit":
            break
        if oper :
            chatAgent.speak(user_input)
            continue


__all__ = ['start']