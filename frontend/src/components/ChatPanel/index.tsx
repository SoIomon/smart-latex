import { useState, useRef, useEffect } from 'react';
import { Input, Button, Typography, Tag, Space } from 'antd';
import { SendOutlined, ClearOutlined, UserOutlined, RobotOutlined } from '@ant-design/icons';
import { useChatStore, createMessageId } from '../../stores/chatStore';
import { useEditorStore } from '../../stores/editorStore';
import { sendChatMessage } from '../../api/chat';

const { Text } = Typography;
const { TextArea } = Input;

const EXAMPLE_PROMPTS = ['把摘要缩短', '添加目录', '调整字体大小', '修正语法错误', '添加参考文献'];

interface ChatPanelProps {
  projectId: string;
}

export default function ChatPanel({ projectId }: ChatPanelProps) {
  const { messages, sending, addMessage, updateLastAssistantMessage, clearMessages, setSending } =
    useChatStore();
  const { setLatexContent } = useEditorStore();
  const [inputValue, setInputValue] = useState('');
  const [agentStatus, setAgentStatus] = useState<string>('');
  const listRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, agentStatus]);

  // Cleanup: abort on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleSend = async (text?: string) => {
    const msg = text || inputValue.trim();
    if (!msg || sending) return;

    setInputValue('');
    setAgentStatus('');

    addMessage({
      id: createMessageId(),
      role: 'user',
      content: msg,
      timestamp: new Date().toISOString(),
    });

    addMessage({
      id: createMessageId(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    });

    // Abort previous request if any
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setSending(true);
    try {
      let fullContent = '';
      let latexUpdate: string | undefined;

      for await (const event of sendChatMessage(projectId, msg, controller.signal)) {
        switch (event.type) {
          case 'thinking':
            setAgentStatus(event.data || '思考中...');
            break;
          case 'tool_call':
            setAgentStatus(`🔧 ${event.data}`);
            break;
          case 'tool_result':
            // Brief flash — status will be replaced by next tool_call or content
            break;
          case 'content':
            // Once real content arrives, clear agent status
            setAgentStatus('');
            fullContent += event.data;
            updateLastAssistantMessage(fullContent, latexUpdate);
            break;
          case 'latex':
            latexUpdate = event.data;
            updateLastAssistantMessage(fullContent, latexUpdate);
            setLatexContent(event.data);
            break;
          case 'error':
            fullContent += `\n错误: ${event.data}`;
            updateLastAssistantMessage(fullContent, latexUpdate);
            break;
          case 'done':
            break;
        }
      }

      setAgentStatus('');
      if (!fullContent) {
        updateLastAssistantMessage('(无响应内容)');
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User cancelled or component unmounted
      } else {
        updateLastAssistantMessage('请求失败，请重试。');
      }
    } finally {
      setAgentStatus('');
      setSending(false);
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        borderLeft: '1px solid #f0f0f0',
      }}
    >
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#fafafa',
        }}
      >
        <Text strong style={{ fontSize: 15 }}>
          AI 助手
        </Text>
        <Button
          size="small"
          icon={<ClearOutlined />}
          onClick={clearMessages}
          disabled={sending}
        >
          清空
        </Button>
      </div>

      <div
        ref={listRef}
        style={{
          flex: 1,
          overflow: 'auto',
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
              试试以下提示词:
            </Text>
            <Space wrap style={{ justifyContent: 'center' }}>
              {EXAMPLE_PROMPTS.map((prompt) => (
                <Tag
                  key={prompt}
                  color="blue"
                  style={{ cursor: 'pointer', padding: '4px 12px' }}
                  onClick={() => handleSend(prompt)}
                >
                  {prompt}
                </Tag>
              ))}
            </Space>
          </div>
        )}
        {messages.map((msg, idx) => (
          <div
            key={msg.id}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            <Space size={4} style={{ marginBottom: 4 }}>
              {msg.role === 'assistant' && (
                <RobotOutlined style={{ color: '#1677ff' }} />
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                {msg.role === 'user' ? '你' : 'AI 助手'}
              </Text>
              {msg.role === 'user' && <UserOutlined style={{ color: '#52c41a' }} />}
            </Space>
            <div
              style={{
                background: msg.role === 'user' ? '#1677ff' : '#f5f5f5',
                color: msg.role === 'user' ? '#fff' : '#333',
                padding: '8px 12px',
                borderRadius: 8,
                maxWidth: '90%',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                fontSize: 13,
                lineHeight: 1.6,
              }}
            >
              {msg.content ||
                (sending && idx === messages.length - 1 && msg.role === 'assistant'
                  ? agentStatus || '思考中...'
                  : '')}
            </div>
            {msg.latex_update && (
              <Tag color="green" style={{ marginTop: 4, fontSize: 12 }}>
                已更新 LaTeX
              </Tag>
            )}
          </div>
        ))}
      </div>

      <div
        style={{
          padding: 12,
          borderTop: '1px solid #f0f0f0',
          background: '#fafafa',
        }}
      >
        <div style={{ display: 'flex', gap: 8 }}>
          <TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="输入消息，按 Enter 发送..."
            autoSize={{ minRows: 1, maxRows: 4 }}
            style={{ flex: 1 }}
            disabled={sending}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => handleSend()}
            loading={sending}
            style={{ alignSelf: 'flex-end' }}
          />
        </div>
      </div>
    </div>
  );
}
