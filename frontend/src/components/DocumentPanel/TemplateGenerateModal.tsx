import { useState, useRef } from 'react';
import { Modal, Input, Button, message, Typography, Upload, Tabs } from 'antd';
import { UploadOutlined, StopOutlined } from '@ant-design/icons';
import { generateTemplate, generateTemplateFromFile } from '../../api/templates';

const { TextArea } = Input;
const { Text } = Typography;

interface TemplateGenerateModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function TemplateGenerateModal({
  open,
  onClose,
  onSuccess,
}: TemplateGenerateModalProps) {
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [generating, setGenerating] = useState(false);
  const [streamOutput, setStreamOutput] = useState('');
  const [extractedDesc, setExtractedDesc] = useState('');
  const [activeTab, setActiveTab] = useState('text');
  const abortRef = useRef<AbortController | null>(null);

  const handleGenerateFromText = async () => {
    if (!description.trim()) {
      message.warning('请输入模板描述');
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setGenerating(true);
    setStreamOutput('');

    try {
      let output = '';
      for await (const event of generateTemplate(description, controller.signal)) {
        if (event.type === 'chunk') {
          output += event.content;
          setStreamOutput(output);
        } else if (event.type === 'done') {
          message.success('模板生成成功');
          onSuccess();
          handleClose();
          return;
        } else if (event.type === 'error') {
          message.error(`生成错误: ${event.content}`);
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        message.info('已停止生成');
      } else {
        message.error('模板生成失败');
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerateFromFile = async () => {
    if (!file) {
      message.warning('请先选择文档');
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setGenerating(true);
    setStreamOutput('');
    setExtractedDesc('');

    try {
      let output = '';
      for await (const event of generateTemplateFromFile(file, controller.signal)) {
        if (event.description) {
          setExtractedDesc(event.description);
          output += `\n--- 提取的格式要求 ---\n${event.description}\n--- 开始生成模板 ---\n`;
          setStreamOutput(output);
        } else if (event.type === 'chunk') {
          output += event.content;
          setStreamOutput(output);
        } else if (event.type === 'done') {
          message.success('模板生成成功');
          onSuccess();
          handleClose();
          return;
        } else if (event.type === 'error') {
          message.error(`生成错误: ${event.content}`);
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        message.info('已停止生成');
      } else {
        message.error('模板生成失败');
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerate = () => {
    if (activeTab === 'file') {
      handleGenerateFromFile();
    } else {
      handleGenerateFromText();
    }
  };

  const handleClose = () => {
    if (generating) {
      abortRef.current?.abort();
    }
    setDescription('');
    setFile(null);
    setStreamOutput('');
    setExtractedDesc('');
    setGenerating(false);
    onClose();
  };

  return (
    <Modal
      title="生成 LaTeX 模板"
      open={open}
      onCancel={handleClose}
      width={640}
      footer={[
        <Button key="cancel" onClick={handleClose}>
          取消
        </Button>,
        generating ? (
          <Button
            key="stop"
            danger
            icon={<StopOutlined />}
            onClick={() => abortRef.current?.abort()}
          >
            停止生成
          </Button>
        ) : (
          <Button
            key="generate"
            type="primary"
            onClick={handleGenerate}
          >
            生成
          </Button>
        ),
      ]}
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'text',
            label: '手动描述',
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Text>
                  描述格式要求（如字体、字号、行距、页边距等）:
                </Text>
                <TextArea
                  rows={4}
                  placeholder="例如：宋体正文、标题三号字、小四号正文、1.5倍行距、A4纸、页边距2.5cm"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  disabled={generating}
                />
              </div>
            ),
          },
          {
            key: 'file',
            label: '从文档导入',
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Text>
                  上传一份模板说明文档或已有格式的 Word/PDF 文档，系统会自动提取格式要求：
                </Text>
                <Upload
                  accept=".docx,.pdf,.md,.txt,.doc"
                  maxCount={1}
                  beforeUpload={(f) => {
                    setFile(f);
                    return false; // prevent auto upload
                  }}
                  onRemove={() => setFile(null)}
                  fileList={file ? [{ uid: '-1', name: file.name, status: 'done' }] : []}
                >
                  <Button icon={<UploadOutlined />} disabled={generating}>
                    选择文档
                  </Button>
                </Upload>
                {extractedDesc && (
                  <div
                    style={{
                      background: '#f6ffed',
                      border: '1px solid #b7eb8f',
                      borderRadius: 6,
                      padding: 12,
                      fontSize: 12,
                    }}
                  >
                    <Text strong style={{ fontSize: 12, color: '#52c41a' }}>
                      提取的格式要求：
                    </Text>
                    <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
                      {extractedDesc}
                    </div>
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />
      {streamOutput && (
        <div
          style={{
            maxHeight: 300,
            overflow: 'auto',
            background: '#f5f5f5',
            borderRadius: 6,
            padding: 12,
            fontSize: 12,
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            marginTop: 12,
          }}
        >
          {streamOutput}
        </div>
      )}
    </Modal>
  );
}
