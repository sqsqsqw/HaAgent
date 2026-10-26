from .chat import ChatAgent

def start():

    chatAgent = ChatAgent()

    while True:
        user_input = input("Human:")
        chatAgent.speak(user_input)


__all__ = ['start']