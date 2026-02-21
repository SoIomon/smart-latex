import { useState, useEffect, useRef } from 'react';
import { Upload, Button, List, Select, Typography, message, Popconfirm, Space } from 'antd';
import {
  UploadOutlined,
  DeleteOutlined,
  FileWordOutlined,
  FilePdfOutlined,
  FileMarkdownOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  PlusOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useDocumentStore } from '../../stores/documentStore';
import { useEditorStore } from '../../stores/editorStore';
import { useProjectStore } from '../../stores/projectStore';
import { getTemplates } from '../../api/templates';
import { generateLatex } from '../../api/generation';
import TemplateGenerateModal from './TemplateGenerateModal';
import type { Template } from '../../types';

const { Text } = Typography;
const { Dragger } = Upload;

interface DocumentPanelProps {
  projectId: string;
  onGenerateStart?: () => void;
  onGenerateDone?: () => void;
}

const fileTypeIcons: Record<string, React.ReactNode> = {
  docx: <FileWordOutlined style={{ color: '#2b579a' }} />,
  doc: <FileWordOutlined style={{ color: '#2b579a' }} />,
  pdf: <FilePdfOutlined style={{ color: '#d32f2f' }} />,
  md: <FileMarkdownOutlined style={{ color: '#333' }} />,
  txt: <FileTextOutlined style={{ color: '#666' }} />,
};

export default function DocumentPanel({ projectId, onGenerateStart, onGenerateDone }: DocumentPanelProps) {
  const { documents, uploading, fetchDocuments, uploadDocument, deleteDocument } =
    useDocumentStore();
  const { setLatexContent, setIsGenerating } = useEditorStore();
  const { currentProject } = useProjectStore();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string | undefined>();
  const [generating, setGenerating] = useState(false);
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const templateInitialized = useRef(false);

  const refreshTemplates = () => {
    getTemplates()
      .then(setTemplates)
      .catch(() => {});
  };

  useEffect(() => {
    fetchDocuments(projectId);
    getTemplates()
      .then(setTemplates)
      .catch(() => {});
  }, [projectId, fetchDocuments]);

  // Initialize selectedTemplate from project's template_id
  useEffect(() => {
    if (!templateInitialized.current && currentProject?.template_id) {
      setSelectedTemplate(currentProject.template_id);
      templateInitialized.current = true;
    }
  }, [currentProject]);

  // Cleanup: abort on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleUpload = async (file: File) => {
    try {
      await uploadDocument(projectId, file);
      message.success(`${file.name} 上传成功`);
    } catch {
      message.error(`${file.name} 上传失败`);
    }
  };

  const [genStatus, setGenStatus] = useState('');

  const handleGenerate = async () => {
    if (documents.length === 0) {
      message.warning('请先上传文档');
      return;
    }

    // Abort previous generation if any
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    onGenerateStart?.();
    setGenerating(true);
    setIsGenerating(true);
    setGenStatus('准备生成...');
    try {
      let content = '';
      for await (const event of generateLatex(
        projectId,
        { template_id: selectedTemplate },
        controller.signal
      )) {
        if (event.type === 'stage') {
          setGenStatus(event.message || '');
        } else if (event.type === 'outline') {
          setGenStatus('大纲规划完成，开始生成章节...');
        } else if (event.type === 'chunk') {
          content += event.content;
          setLatexContent(content);
        } else if (event.type === 'done') {
          // Fix: only override content if done event has non-empty content
          if (event.content) {
            setLatexContent(event.content);
          }
          setGenStatus('');
        } else if (event.type === 'error') {
          message.error(`生成错误: ${event.content}`);
          setGenStatus('');
        }
      }
      message.success('LaTeX 生成完成');
      // Trigger auto-compile after generation is done
      onGenerateDone?.();
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        message.info('已停止生成');
      } else {
        message.error('LaTeX 生成失败');
      }
    } finally {
      setGenerating(false);
      setIsGenerating(false);
      setGenStatus('');
    }
  };

  const getFileExt = (filename: string) => {
    return filename.split('.').pop()?.toLowerCase() || '';
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: 16,
        gap: 16,
      }}
    >
      <Text strong style={{ fontSize: 16 }}>
        文档管理
      </Text>

      <Dragger
        multiple
        showUploadList={false}
        accept=".docx,.pdf,.md,.txt,.doc"
        customRequest={({ file }) => {
          handleUpload(file as File);
        }}
        disabled={uploading}
        style={{ padding: '8px 0' }}
      >
        <p>
          <UploadOutlined style={{ fontSize: 24, color: '#1677ff' }} />
        </p>
        <p style={{ margin: 0, fontSize: 13 }}>点击或拖拽上传文档</p>
        <p style={{ margin: 0, fontSize: 12, color: '#999' }}>
          支持 .docx, .pdf, .md, .txt
        </p>
      </Dragger>

      <List
        size="small"
        dataSource={documents}
        locale={{ emptyText: '暂无文档' }}
        style={{ flex: 1, overflow: 'auto' }}
        renderItem={(doc) => (
          <List.Item style={{ padding: '8px 0' }}>
            <div style={{ display: 'flex', alignItems: 'center', width: '100%', gap: 8 }}>
              <span style={{ flexShrink: 0 }}>
                {fileTypeIcons[getFileExt(doc.original_name || doc.filename)] || <FileTextOutlined />}
              </span>
              <Text ellipsis style={{ flex: 1, minWidth: 0 }}>
                {doc.original_name || doc.filename}
              </Text>
              <Popconfirm
                title="确定删除?"
                onConfirm={() => deleteDocument(projectId, doc.id)}
                okText="删除"
                cancelText="取消"
              >
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  style={{ flexShrink: 0 }}
                />
              </Popconfirm>
            </div>
          </List.Item>
        )}
      />

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Text style={{ fontSize: 13 }}>
            选择模板 (可选)
          </Text>
          <Button
            type="link"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => setTemplateModalOpen(true)}
          >
            生成模板
          </Button>
        </div>
        <Select
          style={{ width: '100%' }}
          placeholder="选择 LaTeX 模板"
          allowClear
          value={selectedTemplate}
          onChange={setSelectedTemplate}
          options={templates.map((t) => ({ label: t.name, value: t.id }))}
        />
      </div>

      {generating ? (
        <Button
          danger
          icon={<StopOutlined />}
          onClick={() => abortRef.current?.abort()}
          block
        >
          停止生成
        </Button>
      ) : (
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={handleGenerate}
          block
        >
          生成 LaTeX
        </Button>
      )}
      {genStatus && (
        <Text type="secondary" style={{ fontSize: 12, textAlign: 'center', display: 'block' }}>
          {genStatus}
        </Text>
      )}

      <TemplateGenerateModal
        open={templateModalOpen}
        onClose={() => setTemplateModalOpen(false)}
        onSuccess={refreshTemplates}
      />
    </div>
  );
}
