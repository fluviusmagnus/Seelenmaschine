import os
import logging
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from chatbot import ChatBot
from utils import remove_blockquote_tags, datetime_str
from config import Config
import threading
import time

# 创建Flask应用
app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)

# 初始化SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# 全局ChatBot实例
_bot = None
_bot_lock = threading.Lock()


def get_bot():
    """获取或创建全局ChatBot实例"""
    global _bot
    with _bot_lock:
        if _bot is None:
            _bot = ChatBot()
    return _bot


@app.route("/")
def index():
    """主页面"""
    try:
        bot = get_bot()
        session_info = bot.get_session_info()

        # 获取历史对话
        existing_conv = bot.get_conversation_history()
        history = []
        if existing_conv:
            for role, text in existing_conv:
                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_blockquote_tags(text)
                    if role == "assistant" and not Config.DEBUG_MODE
                    else text
                )
                history.append(
                    {"role": role, "content": display_text, "timestamp": time.time()}
                )

        return render_template(
            "index.html",
            session_info=session_info,
            history=history,
            ai_name=Config.AI_NAME,
            user_name=Config.USER_NAME,
        )
    except Exception as e:
        logging.error(f"页面加载错误: {str(e)}")
        return render_template("error.html", error="页面加载失败，请检查日志文件")


@app.route("/api/session_info")
def get_session_info():
    """获取会话信息API"""
    try:
        bot = get_bot()
        session_info = bot.get_session_info()
        return jsonify(
            {
                "success": True,
                "data": {
                    "session_id": session_info["session_id"],
                    "start_time": datetime_str(session_info["start_time"]),
                    "current_conv_count": session_info["current_conv_count"],
                },
            }
        )
    except Exception as e:
        logging.error(f"获取会话信息错误: {str(e)}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/tools_status")
def get_tools_status():
    """获取工具调用状态API"""
    try:
        bot = get_bot()
        tools_status = bot.get_tool_calls_status()
        return jsonify({"success": True, "data": {"tools_enabled": tools_status}})
    except Exception as e:
        logging.error(f"获取工具状态错误: {str(e)}")
        return jsonify({"success": False, "error": str(e)})


@socketio.on("connect")
def handle_connect():
    """客户端连接处理"""
    logging.debug("客户端已连接")
    emit("status", {"type": "connected", "message": "连接成功"})


@socketio.on("disconnect")
def handle_disconnect():
    """客户端断开连接处理"""
    logging.debug("客户端已断开连接")


@socketio.on("send_message")
def handle_message(data):
    """处理用户消息"""
    try:
        user_input = data.get("message", "").strip()
        if not user_input:
            emit("error", {"message": "消息不能为空"})
            return

        logging.debug(f"收到用户消息: {user_input}")

        # 发送状态更新
        emit("status", {"type": "processing", "message": "正在思考中..."})

        bot = get_bot()

        # 在后台线程中处理消息以避免阻塞
        def process_message():
            try:
                # 获取AI响应
                response = bot.process_user_input(user_input)

                # 非调试模式下显示清理后的文本
                display_text = (
                    remove_blockquote_tags(response)
                    if not Config.DEBUG_MODE
                    else response
                )

                # 发送响应
                socketio.emit(
                    "message_response",
                    {
                        "user_message": user_input,
                        "ai_response": display_text,
                        "timestamp": time.time(),
                    },
                )

                # 更新会话信息
                session_info = bot.get_session_info()
                socketio.emit(
                    "session_update",
                    {
                        "session_id": session_info["session_id"],
                        "start_time": datetime_str(session_info["start_time"]),
                        "current_conv_count": session_info["current_conv_count"],
                    },
                )

                # 发送完成状态
                socketio.emit("status", {"type": "ready", "message": "就绪"})

            except Exception as e:
                logging.error(f"处理消息错误: {str(e)}")
                socketio.emit("error", {"message": f"处理消息时发生错误: {str(e)}"})
                socketio.emit("status", {"type": "error", "message": "发生错误"})

        # 在新线程中处理消息
        thread = threading.Thread(target=process_message)
        thread.daemon = True
        thread.start()

    except Exception as e:
        logging.error(f"消息处理错误: {str(e)}")
        emit("error", {"message": f"消息处理失败: {str(e)}"})


@socketio.on("reset_session")
def handle_reset_session():
    """重置会话"""
    try:
        logging.debug("收到重置会话请求")
        emit("status", {"type": "processing", "message": "正在重置会话..."})

        bot = get_bot()

        def reset_session():
            try:
                session_info = bot.reset_session()

                socketio.emit(
                    "session_reset",
                    {
                        "session_id": session_info["session_id"],
                        "start_time": datetime_str(session_info["start_time"]),
                        "current_conv_count": session_info["current_conv_count"],
                    },
                )

                socketio.emit("status", {"type": "ready", "message": "会话已重置"})

            except Exception as e:
                logging.error(f"重置会话错误: {str(e)}")
                socketio.emit("error", {"message": f"重置会话失败: {str(e)}"})
                socketio.emit("status", {"type": "error", "message": "重置失败"})

        thread = threading.Thread(target=reset_session)
        thread.daemon = True
        thread.start()

    except Exception as e:
        logging.error(f"重置会话处理错误: {str(e)}")
        emit("error", {"message": f"重置会话失败: {str(e)}"})


@socketio.on("save_session")
def handle_save_session():
    """归档会话"""
    try:
        logging.debug("收到归档会话请求")
        emit("status", {"type": "processing", "message": "正在归档会话，请耐心等待..."})

        bot = get_bot()

        def save_session():
            try:
                session_info = bot.finalize_session()

                socketio.emit(
                    "session_saved",
                    {
                        "session_id": session_info["session_id"],
                        "start_time": datetime_str(session_info["start_time"]),
                        "current_conv_count": session_info["current_conv_count"],
                    },
                )

                socketio.emit(
                    "status", {"type": "ready", "message": "会话已归档，新会话已创建"}
                )

            except Exception as e:
                logging.error(f"归档会话错误: {str(e)}")
                socketio.emit("error", {"message": f"归档会话失败: {str(e)}"})
                socketio.emit("status", {"type": "error", "message": "归档失败"})

        thread = threading.Thread(target=save_session)
        thread.daemon = True
        thread.start()

    except Exception as e:
        logging.error(f"归档会话处理错误: {str(e)}")
        emit("error", {"message": f"归档会话失败: {str(e)}"})


@socketio.on("toggle_tools")
def handle_toggle_tools():
    """切换工具调用权限"""
    try:
        logging.debug("收到切换工具调用权限请求")
        bot = get_bot()
        new_status = bot.toggle_tool_calls()

        emit(
            "tools_toggled",
            {
                "tools_enabled": new_status,
                "message": f"工具调用权限: {'允许' if new_status else '禁止'} (临时设置)",
            },
        )

    except Exception as e:
        logging.error(f"切换工具调用权限错误: {str(e)}")
        emit("error", {"message": f"切换工具调用权限失败: {str(e)}"})


def launch_flask_webui(host="127.0.0.1", port=7860, debug=False):
    """启动Flask Web UI"""
    try:
        logging.info(f"启动Flask Web UI: http://{host}:{port}")
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    except Exception as e:
        logging.error(f"启动Flask Web UI失败: {str(e)}")
        raise


if __name__ == "__main__":
    import sys
    import argparse

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from main import init_logging
    from config import init_config

    # 解析参数
    parser = argparse.ArgumentParser(description="Seelenmaschine Flask Web UI")
    parser.add_argument("profile", help="使用指定的`<profile>.env`配置文件")
    parser.add_argument("--host", default="127.0.0.1", help="主机地址")
    parser.add_argument("--port", type=int, default=7860, help="端口")
    args = parser.parse_args()

    # 初始化配置
    init_config(args.profile)

    # 初始化日志
    init_logging()

    # 启动应用
    launch_flask_webui(host=args.host, port=args.port, debug=Config.DEBUG_MODE)
