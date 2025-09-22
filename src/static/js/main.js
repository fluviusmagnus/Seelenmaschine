// 全局变量
let socket = null;
let isConnected = false;
let autoScroll = true;
let currentTheme = 'light';

// DOM元素
const elements = {
    messageInput: null,
    sendBtn: null,
    chatContainer: null,
    chatMessages: null,
    typingIndicator: null,
    statusIndicator: null,
    statusText: null,
    sessionId: null,
    startTime: null,
    convCount: null,
    resetBtn: null,
    saveBtn: null,
    clearInputBtn: null,
    darkModeToggle: null,
    autoScrollToggle: null,
    charCount: null,
    confirmModal: null,
    confirmModalBody: null,
    confirmModalConfirm: null,
    errorToast: null,
    successToast: null,
    errorMessage: null,
    successMessage: null,
    sidebarToggle: null,
    sidebar: null,
    sidebarOverlay: null
};

// 初始化函数
function initializeChat() {
    console.log('初始化聊天界面...');

    // 获取DOM元素
    initializeElements();

    // 初始化Socket.IO连接
    initializeSocket();

    // 绑定事件监听器
    bindEventListeners();

    // 初始化设置
    initializeSettings();

    console.log('聊天界面初始化完成');
}

// 获取DOM元素
function initializeElements() {
    elements.messageInput = document.getElementById('message-input');
    elements.sendBtn = document.getElementById('send-btn');
    elements.chatContainer = document.getElementById('chat-container');
    elements.chatMessages = document.getElementById('chat-messages');
    elements.typingIndicator = document.getElementById('typing-indicator');
    elements.statusIndicator = document.getElementById('status-indicator');
    elements.statusText = document.getElementById('status-text');
    elements.sessionId = document.getElementById('session-id');
    elements.startTime = document.getElementById('start-time');
    elements.convCount = document.getElementById('conv-count');
    elements.resetBtn = document.getElementById('reset-btn');
    elements.saveBtn = document.getElementById('save-btn');
    elements.clearInputBtn = document.getElementById('clear-input-btn');
    elements.darkModeToggle = document.getElementById('dark-mode-toggle');
    elements.autoScrollToggle = document.getElementById('auto-scroll-toggle');
    elements.charCount = document.getElementById('char-count');
    elements.confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
    elements.confirmModalBody = document.getElementById('confirmModalBody');
    elements.confirmModalConfirm = document.getElementById('confirmModalConfirm');
    elements.errorToast = new bootstrap.Toast(document.getElementById('error-toast'));
    elements.successToast = new bootstrap.Toast(document.getElementById('success-toast'));
    elements.errorMessage = document.getElementById('error-message');
    elements.successMessage = document.getElementById('success-message');
    elements.sidebarToggle = document.getElementById('sidebar-toggle');
    elements.sidebar = document.getElementById('sidebar');
    elements.sidebarOverlay = document.getElementById('sidebar-overlay');
}

// 初始化Socket.IO连接
function initializeSocket() {
    console.log('连接到服务器...');

    socket = io();

    // 连接事件
    socket.on('connect', function () {
        console.log('已连接到服务器');
        isConnected = true;
        updateStatus('connected', '已连接');
    });

    socket.on('disconnect', function () {
        console.log('与服务器断开连接');
        isConnected = false;
        updateStatus('error', '连接断开');
    });

    // 状态更新
    socket.on('status', function (data) {
        console.log('状态更新:', data);
        updateStatus(data.type, data.message);
    });

    // 消息响应
    socket.on('message_response', function (data) {
        console.log('收到消息响应:', data);
        hideTypingIndicator();
        addMessage('user', data.user_message, data.timestamp);
        addMessage('assistant', data.ai_response, data.timestamp + 0.1);
        clearInput();
    });

    // 会话更新
    socket.on('session_update', function (data) {
        console.log('会话信息更新:', data);
        updateSessionInfo(data);
    });

    // 会话重置
    socket.on('session_reset', function (data) {
        console.log('会话已重置:', data);
        clearChatMessages();
        updateSessionInfo(data);
        // 重新启用所有按钮
        setButtonState(elements.sendBtn, true);
        setButtonState(elements.resetBtn, true);
        setButtonState(elements.saveBtn, true);
        showSuccessToast('会话已重置');
    });

    // 会话归档
    socket.on('session_saved', function (data) {
        console.log('会话已归档:', data);
        clearChatMessages();
        updateSessionInfo(data);
        // 重新启用所有按钮
        setButtonState(elements.sendBtn, true);
        setButtonState(elements.resetBtn, true);
        setButtonState(elements.saveBtn, true);
        showSuccessToast('会话已归档，新会话已创建');
    });

    // 错误处理
    socket.on('error', function (data) {
        console.error('服务器错误:', data);
        hideTypingIndicator();
        showErrorToast(data.message || '发生未知错误');
    });
}

// 绑定事件监听器
function bindEventListeners() {
    // 发送消息
    if (elements.sendBtn) {
        elements.sendBtn.addEventListener('click', sendMessage);
    }

    // 输入框事件
    if (elements.messageInput) {
        elements.messageInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        elements.messageInput.addEventListener('input', function () {
            updateCharCount();
        });
    }

    // 会话管理按钮
    if (elements.resetBtn) {
        elements.resetBtn.addEventListener('click', function () {
            showConfirmDialog('重置会话', '确定要重置当前会话吗？这将清除所有对话历史。', function () {
                resetSession();
            });
        });
    }

    if (elements.saveBtn) {
        elements.saveBtn.addEventListener('click', function () {
            showConfirmDialog('归档会话', '确定要归档当前会话吗？这将保存当前会话并开始新的对话。', function () {
                saveSession();
            });
        });
    }

    if (elements.clearInputBtn) {
        elements.clearInputBtn.addEventListener('click', clearInput);
    }

    // 设置切换
    if (elements.darkModeToggle) {
        elements.darkModeToggle.addEventListener('change', toggleDarkMode);
    }

    if (elements.autoScrollToggle) {
        elements.autoScrollToggle.addEventListener('change', function () {
            autoScroll = this.checked;
            localStorage.setItem('autoScroll', autoScroll);
        });
    }

    // 侧边栏切换
    if (elements.sidebarToggle) {
        elements.sidebarToggle.addEventListener('click', toggleSidebar);
    }

    if (elements.sidebarOverlay) {
        elements.sidebarOverlay.addEventListener('click', hideSidebar);
    }
}

// 切换侧边栏显示
function toggleSidebar() {
    if (elements.sidebar && elements.sidebarOverlay) {
        const isVisible = elements.sidebar.classList.contains('show');
        if (isVisible) {
            hideSidebar();
        } else {
            showSidebar();
        }
    }
}

// 显示侧边栏
function showSidebar() {
    if (elements.sidebar && elements.sidebarOverlay) {
        elements.sidebar.classList.add('show');
        elements.sidebarOverlay.classList.add('show');
        document.body.style.overflow = 'hidden';
    }
}

// 隐藏侧边栏
function hideSidebar() {
    if (elements.sidebar && elements.sidebarOverlay) {
        elements.sidebar.classList.remove('show');
        elements.sidebarOverlay.classList.remove('show');
        document.body.style.overflow = '';
    }
}

// 初始化设置
function initializeSettings() {
    // 恢复深色模式设置
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        currentTheme = savedTheme;
        if (currentTheme === 'dark') {
            document.documentElement.setAttribute('data-bs-theme', 'dark');
            if (elements.darkModeToggle) {
                elements.darkModeToggle.checked = true;
            }
        }
    }

    // 恢复自动滚动设置
    const savedAutoScroll = localStorage.getItem('autoScroll');
    if (savedAutoScroll !== null) {
        autoScroll = savedAutoScroll === 'true';
        if (elements.autoScrollToggle) {
            elements.autoScrollToggle.checked = autoScroll;
        }
    }

    // 更新字符计数
    updateCharCount();
}

// 发送消息
function sendMessage() {
    if (!isConnected) {
        showErrorToast('未连接到服务器');
        return;
    }

    const message = elements.messageInput.value.trim();
    if (!message) {
        showErrorToast('请输入消息内容');
        return;
    }

    console.log('发送消息:', message);

    // 显示输入指示器
    showTypingIndicator();

    // 发送消息到服务器
    socket.emit('send_message', { message: message });

    // 禁用发送按钮
    setButtonState(elements.sendBtn, false);
}

// 重置会话
function resetSession() {
    if (!isConnected) {
        showErrorToast('未连接到服务器');
        return;
    }

    console.log('重置会话');
    socket.emit('reset_session');
    setButtonState(elements.resetBtn, false);
}

// 归档会话
function saveSession() {
    if (!isConnected) {
        showErrorToast('未连接到服务器');
        return;
    }

    console.log('归档会话');
    socket.emit('save_session');
    setButtonState(elements.saveBtn, false);
}

// 添加消息到聊天界面
function addMessage(role, content, timestamp) {
    const messageContainer = document.createElement('div');
    messageContainer.className = 'message-container mb-3';
    messageContainer.setAttribute('data-timestamp', timestamp);

    const message = document.createElement('div');
    message.className = `message ${role === 'assistant' ? 'ai-message' : 'user-message'}`;

    // 消息头部
    const header = document.createElement('div');
    header.className = 'message-header';

    if (role === 'assistant') {
        header.innerHTML = `
            <div class="avatar user-avatar" style="background: var(--primary-color);">
                <i class="bi bi-robot"></i>
            </div>
            <span class="sender-name">${window.AI_NAME || 'Seelenmaschine'}</span>
            <span class="timestamp">${formatTimestamp(timestamp)}</span>
        `;
    } else {
        header.innerHTML = `
            <div class="avatar user-avatar">
                <i class="bi bi-person-fill"></i>
            </div>
            <span class="sender-name">${window.USER_NAME || '用户'}</span>
            <span class="timestamp">${formatTimestamp(timestamp)}</span>
        `;
    }

    // 消息内容
    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';

    if (role === 'assistant') {
        const markdownContent = document.createElement('div');
        markdownContent.className = 'markdown-content';
        markdownContent.innerHTML = marked.parse(content);

        // 高亮代码块
        markdownContent.querySelectorAll('pre code').forEach(function (block) {
            hljs.highlightElement(block);
        });

        messageContent.appendChild(markdownContent);
    } else {
        const textContent = document.createElement('div');
        textContent.className = 'text-content';
        textContent.textContent = content;
        messageContent.appendChild(textContent);
    }

    message.appendChild(header);
    message.appendChild(messageContent);
    messageContainer.appendChild(message);

    elements.chatMessages.appendChild(messageContainer);

    // 自动滚动到底部
    if (autoScroll) {
        scrollToBottom();
    }
}

// 显示输入指示器
function showTypingIndicator() {
    if (elements.typingIndicator) {
        elements.typingIndicator.style.display = 'block';
        if (autoScroll) {
            scrollToBottom();
        }
    }
}

// 隐藏输入指示器
function hideTypingIndicator() {
    if (elements.typingIndicator) {
        elements.typingIndicator.style.display = 'none';
    }

    // 重新启用按钮
    setButtonState(elements.sendBtn, true);
    setButtonState(elements.resetBtn, true);
    setButtonState(elements.saveBtn, true);
}

// 清除聊天消息
function clearChatMessages() {
    if (elements.chatMessages) {
        elements.chatMessages.innerHTML = '';
    }
}

// 清除输入框
function clearInput() {
    if (elements.messageInput) {
        elements.messageInput.value = '';
        updateCharCount();
        elements.messageInput.focus();
    }
}

// 更新状态指示器
function updateStatus(type, message) {
    if (!elements.statusIndicator || !elements.statusText) return;

    // 移除所有状态类
    elements.statusIndicator.className = 'badge';

    // 添加对应的状态类
    switch (type) {
        case 'connected':
        case 'ready':
            elements.statusIndicator.classList.add('bg-success');
            break;
        case 'processing':
            elements.statusIndicator.classList.add('bg-info');
            break;
        case 'error':
            elements.statusIndicator.classList.add('bg-danger');
            break;
        default:
            elements.statusIndicator.classList.add('bg-warning');
    }

    elements.statusText.textContent = message;
}

// 更新会话信息
function updateSessionInfo(data) {
    if (elements.sessionId) {
        elements.sessionId.textContent = data.session_id;
    }
    if (elements.startTime) {
        elements.startTime.textContent = data.start_time;
    }
    if (elements.convCount) {
        elements.convCount.textContent = data.current_conv_count;
    }
}

// 更新字符计数
function updateCharCount() {
    if (elements.charCount && elements.messageInput) {
        const count = elements.messageInput.value.length;
        elements.charCount.textContent = count;
    }
}

// 滚动到底部
function scrollToBottom() {
    if (elements.chatContainer) {
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    }
}

// 格式化时间戳
function formatTimestamp(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

// 设置按钮状态
function setButtonState(button, enabled) {
    if (!button) return;

    if (enabled) {
        button.disabled = false;
        button.classList.remove('loading');
    } else {
        button.disabled = true;
        button.classList.add('loading');
    }
}

// 切换深色模式
function toggleDarkMode() {
    if (currentTheme === 'light') {
        currentTheme = 'dark';
        document.documentElement.setAttribute('data-bs-theme', 'dark');
    } else {
        currentTheme = 'light';
        document.documentElement.removeAttribute('data-bs-theme');
    }

    localStorage.setItem('theme', currentTheme);
}

// 显示确认对话框
function showConfirmDialog(title, message, onConfirm) {
    if (!elements.confirmModal) return;

    document.getElementById('confirmModalLabel').textContent = title;
    elements.confirmModalBody.textContent = message;

    // 移除之前的事件监听器
    const newConfirmBtn = elements.confirmModalConfirm.cloneNode(true);
    elements.confirmModalConfirm.parentNode.replaceChild(newConfirmBtn, elements.confirmModalConfirm);
    elements.confirmModalConfirm = newConfirmBtn;

    // 添加新的事件监听器
    elements.confirmModalConfirm.addEventListener('click', function () {
        elements.confirmModal.hide();
        if (onConfirm) {
            onConfirm();
        }
    });

    elements.confirmModal.show();
}

// 显示错误提示
function showErrorToast(message) {
    if (elements.errorMessage && elements.errorToast) {
        elements.errorMessage.textContent = message;
        elements.errorToast.show();
    }
}

// 显示成功提示
function showSuccessToast(message) {
    if (elements.successMessage && elements.successToast) {
        elements.successMessage.textContent = message;
        elements.successToast.show();
    }
}

// 导出函数供全局使用
window.initializeChat = initializeChat;
window.sendMessage = sendMessage;
window.clearInput = clearInput;
window.toggleDarkMode = toggleDarkMode;

// 页面加载完成后自动初始化
document.addEventListener('DOMContentLoaded', function () {
    console.log('页面加载完成，准备初始化聊天界面');
});
