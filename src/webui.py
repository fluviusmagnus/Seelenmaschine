import gradio as gr
from chatbot import ChatBot
from utils import remove_blockquote_tags, datetime_str
from config import Config
import logging

# 全局ChatBot实例
_bot = None


def get_bot():
    """获取或创建全局ChatBot实例"""
    global _bot
    if _bot is None:
        _bot = ChatBot()
    return _bot


def create_webui():
    try:
        bot = get_bot()

        # 显示会话信息
        session_info = bot.get_session_info()
        initial_info = f"当前会话ID: {session_info['session_id']}\n"
        initial_info += f"开始时间: {datetime_str(session_info['start_time'])}\n\n"

        # 显示历史对话
        existing_conv = bot.get_conversation_history()
        history = []
        if existing_conv:
            initial_info += f"已载入最后{len(existing_conv)}条历史对话"
            for role, text in existing_conv:
                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_blockquote_tags(text)
                    if role == "assistant" and not Config.DEBUG_MODE
                    else text
                )
                history.append({"role": role, "content": display_text})

        def process_message(message, history):
            if not message:
                return history

            try:
                # 获取AI响应
                response = bot.process_user_input(message)

                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_blockquote_tags(response)
                    if not Config.DEBUG_MODE
                    else response
                )

                # 更新对话历史
                history = history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": display_text},
                ]
                return history
            except Exception as e:
                logging.error(f"运行时错误: {str(e)}")
                history = history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": "发生错误,请检查日志文件"},
                ]
                return history

        def handle_reset():
            try:
                session_info = bot.reset_session()
                info = "当前会话已重置\n"
                info += f"当前会话ID: {session_info['session_id']}\n"
                info += f"开始时间: {datetime_str(session_info['start_time'])}"
                return info, []
            except Exception as e:
                logging.error(f"重置会话错误: {str(e)}")
                return "发生错误,请检查日志文件", []

        def handle_save():
            try:
                session_info = bot.finalize_session()
                info = "当前会话已归档,创建新会话\n"
                info += f"当前会话ID: {session_info['session_id']}\n"
                info += f"开始时间: {datetime_str(session_info['start_time'])}"
                return info, []
            except Exception as e:
                logging.error(f"归档会话错误: {str(e)}")
                return "发生错误,请检查日志文件", []

        # 创建聊天界面
        with gr.Blocks(title=f"Seelenmaschine - {Config.AI_NAME}") as interface:
            gr.Markdown(f"# Seelenmaschine - 与{Config.AI_NAME}对话")

            with gr.Accordion(label="显示/隐藏系统信息", open=True):
                info = gr.Textbox(
                    value=initial_info,
                    label="系统信息",
                    lines=4,
                    interactive=False,
                )

            chatbot = gr.Chatbot(
                value=history,
                label="对话历史",
                type="messages",
                autosave=True,  # 启用自动保存
            )

            msg = gr.Textbox(
                label="输入消息",
                placeholder="输入消息开始对话(按Enter发送,Shift+Enter换行)",
                lines=1,
                interactive=True,
            )

            with gr.Row():
                submit = gr.Button("发送消息", variant="primary")
                clear_btn = gr.Button("清除消息")
                save_btn = gr.Button("归档会话")
                reset_btn = gr.Button("重置会话", variant="stop")

            # 绑定事件处理
            clear_btn.click(fn=lambda: "", outputs=msg)  # 清除输入框内容

            msg.submit(
                fn=process_message,
                inputs=[msg, chatbot],
                outputs=chatbot,
                show_progress=True,
            ).then(fn=lambda: None, outputs=msg)

            submit.click(
                fn=process_message,
                inputs=[msg, chatbot],
                outputs=chatbot,
                show_progress=True,
            ).then(fn=lambda: None, outputs=msg)

            reset_btn.click(fn=handle_reset, outputs=[info, chatbot])

            save_btn.click(fn=handle_save, outputs=[info, chatbot])

        return interface

    except Exception as e:
        logging.error(f"初始化错误: {str(e)}")
        raise


def launch_webui(host="127.0.0.1", port=7860):
    interface = create_webui()
    interface.launch(
        server_name=host,
        server_port=port,
        share=False,
        pwa=True,
        favicon_path=str(Config.BASE_DIR / "static" / "logo-transparent.png"),
        state_directory=str(Config.BASE_DIR / "states"),  # 添加状态存储目录
    )
