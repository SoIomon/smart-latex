import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, Space, message, Spin, Switch, Typography, Tooltip } from 'antd';
import {
  SaveOutlined,
  PlayCircleOutlined,
  DownloadOutlined,
  ArrowLeftOutlined,
  BugOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  CloseOutlined,
  FileWordOutlined,
} from '@ant-design/icons';
import { useProjectStore } from '../../stores/projectStore';
import { useEditorStore } from '../../stores/editorStore';
import { useChatStore } from '../../stores/chatStore';
import { compileLatex, compileAndFix, getPdfUrl, downloadPdf, downloadWord } from '../../api/compiler';
import DocumentPanel from '../../components/DocumentPanel';
import EditorPanel from '../../components/Editor';
import ChatPanel from '../../components/ChatPanel';

const { Text } = Typography;

const AUTO_COMPILE_DELAY = 5000; // 5 seconds debounce

export default function Workspace() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { currentProject, fetchProject, updateProject } = useProjectStore();
  const {
    latexContent,
    setLatexContent,
    compiling,
    setCompiling,
    setCompileResult,
    setPdfUrl,
    isGenerating,
    compileErrors,
    setCompileErrors,
    compileLog,
    setCompileLog,
  } = useEditorStore();
  const { clearMessages } = useChatStore();
  const [saving, setSaving] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [compileStatus, setCompileStatus] = useState('');
  const [autoCompile, setAutoCompile] = useState(true);
  const [autoFix, setAutoFix] = useState(true);
  const [showErrorPanel, setShowErrorPanel] = useState(false);
  const autoCompileTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastCompiledRef = useRef('');
  const latexContentRef = useRef(latexContent);
  latexContentRef.current = latexContent;
  const autoFixRef = useRef(autoFix);
  autoFixRef.current = autoFix;
  const compileAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!projectId) return;
    fetchProject(projectId);
    return () => {
      clearMessages();
    };
  }, [projectId, fetchProject, clearMessages]);

  useEffect(() => {
    if (currentProject) {
      setLatexContent(currentProject.latex_content || '');
    }
  }, [currentProject, setLatexContent]);

  // Cleanup: abort compile on unmount
  useEffect(() => {
    return () => {
      compileAbortRef.current?.abort();
      if (autoCompileTimer.current) {
        clearTimeout(autoCompileTimer.current);
      }
    };
  }, []);

  const handleSave = useCallback(async () => {
    if (!projectId) return;
    setSaving(true);
    try {
      await updateProject(projectId, { latex_content: latexContentRef.current });
      message.success('保存成功');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  }, [projectId, updateProject]);

  const handleCompile = useCallback(async () => {
    if (!projectId) return;
    const content = latexContentRef.current;
    if (!content.trim()) return;

    // Abort previous compile if any
    compileAbortRef.current?.abort();
    const controller = new AbortController();
    compileAbortRef.current = controller;

    setCompiling(true);
    setCompileResult(null);
    setCompileErrors([]);
    setCompileLog('');
    setCompileStatus('编译中...');
    lastCompiledRef.current = content;

    try {
      if (autoFixRef.current) {
        // AI 修正模式：编译失败时自动用 LLM 修正并重试
        for await (const event of compileAndFix(projectId, content, controller.signal)) {
          if (event.type === 'status') {
            setCompileStatus(event.data.message);
          } else if (event.type === 'fix') {
            if (event.data.latex_content) {
              setLatexContent(event.data.latex_content);
              lastCompiledRef.current = event.data.latex_content;
            }
            setCompileStatus(event.data.message);
          } else if (event.type === 'done') {
            if (event.data.success) {
              setPdfUrl(getPdfUrl(projectId) + '?t=' + Date.now());
              const msg = event.data.attempts && event.data.attempts > 1
                ? `编译成功（AI 修正了 ${event.data.attempts - 1} 次）`
                : '编译成功';
              message.success(msg);
              if (event.data.latex_content && event.data.attempts && event.data.attempts > 1) {
                setLatexContent(event.data.latex_content);
                lastCompiledRef.current = event.data.latex_content;
              }
              setShowErrorPanel(false);
              setCompileErrors([]);
              setCompileLog('');
            } else {
              message.error(event.data.message || '编译失败');
              if (event.data.errors && event.data.errors.length > 0) {
                setCompileErrors(event.data.errors);
                setShowErrorPanel(true);
              }
              if (event.data.log) {
                setCompileLog(event.data.log);
                setShowErrorPanel(true);
              }
            }
            setCompileStatus('');
          }
        }
      } else {
        // 纯编译模式：不调用 AI 修正
        const result = await compileLatex(projectId, content);
        if (result.success) {
          setPdfUrl(getPdfUrl(projectId) + '?t=' + Date.now());
          message.success('编译成功');
          setShowErrorPanel(false);
          setCompileErrors([]);
          setCompileLog('');
        } else {
          message.error('编译失败');
          if (result.errors && result.errors.length > 0) {
            setCompileErrors(result.errors);
            setShowErrorPanel(true);
          }
          if (result.log) {
            setCompileLog(result.log);
            setShowErrorPanel(true);
          }
        }
        setCompileStatus('');
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // Cancelled
      } else {
        message.error('编译请求失败');
      }
      setCompileStatus('');
    } finally {
      setCompiling(false);
    }
  }, [projectId, setCompiling, setCompileResult, setPdfUrl, setLatexContent, setCompileErrors, setCompileLog]);

  // Auto-compile: debounce on latexContent change, pause during generation
  useEffect(() => {
    if (!autoCompile || !latexContent.trim() || compiling || isGenerating || latexContent === lastCompiledRef.current) return;

    if (autoCompileTimer.current) {
      clearTimeout(autoCompileTimer.current);
    }

    autoCompileTimer.current = setTimeout(() => {
      handleCompile();
    }, AUTO_COMPILE_DELAY);

    return () => {
      if (autoCompileTimer.current) {
        clearTimeout(autoCompileTimer.current);
      }
    };
  }, [latexContent, autoCompile, compiling, isGenerating, handleCompile]);

  // Ctrl+S / Cmd+S save shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleSave]);

  const handleDownload = async () => {
    if (!projectId) return;
    try {
      await downloadPdf(projectId);
    } catch {
      message.error('下载失败，请先编译');
    }
  };

  const handleDownloadWord = async () => {
    if (!projectId) return;
    try {
      await downloadWord(projectId);
    } catch {
      message.error('导出 Word 失败');
    }
  };

  // Abort compile when generation starts
  const handleGenerateStart = useCallback(() => {
    compileAbortRef.current?.abort();
    if (autoCompileTimer.current) {
      clearTimeout(autoCompileTimer.current);
    }
    setCompiling(false);
    setCompileStatus('');
  }, [setCompiling]);

  // Auto-compile after generation done
  const handleGenerateDone = useCallback(() => {
    handleCompile();
  }, [handleCompile]);

  if (!projectId) {
    navigate('/');
    return null;
  }

  if (!currentProject) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
        }}
      >
        <Spin size="large" tip="加载项目中..." />
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
      }}
    >
      {/* Workspace Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 16px',
          borderBottom: '1px solid #f0f0f0',
          background: '#fff',
        }}
      >
        <Space>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
          />
          <Text strong style={{ fontSize: 16 }}>
            {currentProject.name}
          </Text>
          {compileStatus && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              <BugOutlined spin={compiling} /> {compileStatus}
            </Text>
          )}
        </Space>
        <Space>
          <Tooltip title="编辑后自动编译（5秒延迟）">
            <Space size={4}>
              <Text style={{ fontSize: 12 }}>自动编译</Text>
              <Switch
                size="small"
                checked={autoCompile}
                onChange={setAutoCompile}
              />
            </Space>
          </Tooltip>
          <Tooltip title="编译失败时 AI 自动修正错误并重试">
            <Space size={4}>
              <Text style={{ fontSize: 12 }}>AI 修正</Text>
              <Switch
                size="small"
                checked={autoFix}
                onChange={setAutoFix}
              />
            </Space>
          </Tooltip>
          <Tooltip title="保存 (Ctrl+S)">
            <Button icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
              保存
            </Button>
          </Tooltip>
          <Tooltip title={autoFix ? "编译（失败时 AI 自动修正）" : "编译"}>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleCompile}
              loading={compiling}
            >
              编译
            </Button>
          </Tooltip>
          <Tooltip title="下载 PDF">
            <Button icon={<DownloadOutlined />} onClick={handleDownload}>
              导出 PDF
            </Button>
          </Tooltip>
          <Tooltip title="导出 Word 文档">
            <Button icon={<FileWordOutlined />} onClick={handleDownloadWord}>
              导出 Word
            </Button>
          </Tooltip>
        </Space>
      </div>

      {/* Three-column Layout */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left: Document Panel */}
        <div
          style={{
            width: leftCollapsed ? 0 : 300,
            borderRight: leftCollapsed ? 'none' : '1px solid #f0f0f0',
            background: '#fff',
            overflow: 'hidden',
            transition: 'width 0.2s ease',
            flexShrink: 0,
          }}
        >
          <div style={{ width: 300, height: '100%', overflow: 'auto' }}>
            <DocumentPanel projectId={projectId} onGenerateStart={handleGenerateStart} onGenerateDone={handleGenerateDone} />
          </div>
        </div>
        <Tooltip title={leftCollapsed ? '展开文档面板' : '收起文档面板'}>
          <div
            onClick={() => setLeftCollapsed((c) => !c)}
            style={{
              width: 16,
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              borderRight: '1px solid #f0f0f0',
              background: '#fafafa',
              fontSize: 12,
              color: '#999',
            }}
          >
            {leftCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
        </Tooltip>

        {/* Center: Editor + Preview + Error Panel */}
        <div style={{ flex: 1, overflow: 'hidden', background: '#fff', display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <EditorPanel />
          </div>
          {/* Compile Error Panel */}
          {showErrorPanel && (compileErrors.length > 0 || compileLog) && (
            <div
              style={{
                borderTop: '1px solid #f0f0f0',
                background: '#fff7f7',
                maxHeight: 200,
                overflow: 'auto',
                padding: '8px 16px',
                fontSize: 12,
                fontFamily: '"Fira Code", "Consolas", monospace',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <Text strong style={{ fontSize: 13, color: '#ff4d4f' }}>
                  编译错误
                </Text>
                <Button
                  type="text"
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={() => setShowErrorPanel(false)}
                />
              </div>
              {compileErrors.map((err, i) => (
                <div key={i} style={{ color: '#ff4d4f', marginBottom: 4, whiteSpace: 'pre-wrap' }}>
                  {err}
                </div>
              ))}
              {compileLog && (
                <div style={{ color: '#666', whiteSpace: 'pre-wrap', marginTop: 8 }}>
                  {compileLog}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Chat Panel with collapse button */}
        <Tooltip title={rightCollapsed ? '展开 AI 面板' : '收起 AI 面板'}>
          <div
            onClick={() => setRightCollapsed((c) => !c)}
            style={{
              width: 16,
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              borderLeft: '1px solid #f0f0f0',
              background: '#fafafa',
              fontSize: 12,
              color: '#999',
            }}
          >
            {rightCollapsed ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
          </div>
        </Tooltip>
        <div
          style={{
            width: rightCollapsed ? 0 : 350,
            background: '#fff',
            overflow: 'hidden',
            transition: 'width 0.2s ease',
            flexShrink: 0,
          }}
        >
          <div style={{ width: 350, height: '100%', overflow: 'hidden' }}>
            <ChatPanel projectId={projectId} />
          </div>
        </div>
      </div>
    </div>
  );
}
