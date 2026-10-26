
from textual.app import App, ComposeResult
from textual.widgets import Input, Static
from textual.containers import Vertical


class CodeAgentApp(App):
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="chat_log")  # 给id，后面通过id查
            yield Input(placeholder="输入指令，Ctrl+C打断agent...", id="user_input")

    def on_mount(self) -> None:
        """界面挂载完成后，缓存控件引用（推荐在这里拿）"""
        self.chat_log = self.query_one("#chat_log", Static)
        self.user_input = self.query_one("#user_input", Input)

    def add_log(self, text: str):
        """追加日志，后面给Agent回调用"""
        # Static 更新内容用 .update()
        self.chat_log.update(self.chat_log.renderable + "\n" + text)

def main():
    app = CodeAgentApp()
    app.run()

if __name__ == "__main__":
    main()
__all__ = ["main"]