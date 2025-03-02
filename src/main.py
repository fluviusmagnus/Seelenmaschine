import logging
import argparse
from config import Config
from utils import remove_blockquote_tags
from chatbot import ChatBot
from webui import launch_webui
import os

if os.name in ["posix"]:
    import readline


def init_logging():
    os.makedirs(os.path.dirname(Config.LOG_PATH), exist_ok=True)
    # 配置根日志记录器
    logging.basicConfig(
        filename=Config.LOG_PATH,
        level=logging.DEBUG if Config.DEBUG_MODE else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # 设置网络通信的日志级别为WARNING
    for logger_name in [
        "httpx",
        "httpcore",
        "httpcore.http11",
        "httpcore.connection",
        "openai",
        "asyncio",
        "urllib3.connectionpool",
    ]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def parse_args():
    parser = argparse.ArgumentParser(description="Seelenmaschine CLI/WebUI")
    parser.add_argument("--webui", action="store_true", help="启动Web界面")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Web界面主机地址 (默认: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=7860, help="Web界面端口 (默认: 7860)"
    )
    return parser.parse_args()


def main():
    try:
        bot = ChatBot()

        # 显示会话信息
        session_info = bot.get_session_info()
        logging.debug(f"初始化应用并载入会话ID: {session_info['session_id']}")
        print(f"\n当前会话ID: {session_info['session_id']}")
        print(f"开始时间: {session_info['start_time']}")

        # 显示历史对话
        existing_conv = bot.get_conversation_history()
        if existing_conv:
            print(f"\n最后{len(existing_conv)}条历史对话:")
            for role, text in existing_conv:
                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_blockquote_tags(text)
                    if role == "assistant" and not Config.DEBUG_MODE
                    else text
                )
                print(
                    f"{Config.AI_NAME if role == 'assistant' else Config.USER_NAME}: {display_text}"
                )
        print("\n输入消息开始对话(输入 /help 或 /h 查看可用命令)")

        # 主循环
        while True:
            try:
                user_input = input("\n> ").strip()
                if not user_input:
                    continue

                # 处理命令
                if user_input.startswith("/"):
                    if handle_command(user_input, bot):
                        continue

                # 获取AI响应
                response = bot.process_user_input(user_input)

                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_blockquote_tags(response)
                    if not Config.DEBUG_MODE
                    else response
                )
                print(f"\n{Config.AI_NAME}: {display_text}")

            except KeyboardInterrupt:
                logging.debug("用户中断程序")
                exit()
            except Exception as e:
                logging.error(f"运行时错误: {str(e)}")
                print("发生错误,请检查日志文件")

    except Exception as e:
        logging.error(f"初始化错误: {str(e)}")
        print("初始化过程中发生错误,请检查日志文件")


def handle_command(command: str, bot: ChatBot) -> bool:
    """处理用户命令"""
    logging.debug(f"处理用户命令: {command}")
    if command in {"/help", "/h"}:
        print("\n可用命令:")
        print("/reset, /r         - 重置当前会话")
        print("/save, /s          - 归档当前会话,开始新会话")
        print("/saveandexit, /sq  - 归档当前会话,退出程序")
        print("/exit, /quit, /q   - 暂存当前状态并退出程序")
        print("/help, /h          - 显示此帮助信息")
        return True
    elif command in {"/reset", "/r"}:
        session_info = bot.reset_session()
        print("\n当前会话已重置")
        print(f"当前会话ID: {session_info['session_id']}")
        print(f"开始时间: {session_info['start_time']}")
        return True
    elif command in {"/save", "/s"}:
        print("\n正在归档,请耐心等待……")
        session_info = bot.finalize_session()
        print("当前会话已归档,创建新会话")
        print(f"当前会话ID: {session_info['session_id']}")
        print(f"开始时间: {session_info['start_time']}")
        return True
    elif command in {"/saveandexit", "/sq"}:
        print("\n正在归档,请耐心等待……")
        bot.finalize_session()
        logging.debug("用户请求归档并退出")
        print("当前会话已归档,再见")
        exit()
    elif command in {"/exit", "/quit", "/q"}:
        logging.debug("用户请求退出")
        print("\n会话已暂存,下次启动将恢复当前状态")
        exit()
    return False


init_logging()
if __name__ == "__main__":
    args = parse_args()
    if args.webui:
        launch_webui(args.host, args.port)
    else:
        main()
