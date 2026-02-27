import { useState, useRef, useEffect } from 'react';
import { Input, Button, message } from 'antd';
import { EditOutlined, LoadingOutlined } from '@ant-design/icons';
import { editSelection } from '../../api/selection';
import { useProjectStore } from '../../stores/projectStore';

interface SelectionToolbarProps {
  visible: boolean;
  position: { top: number; left: number };
  selectedText: string;
  selectionFrom: number;
  selectionTo: number;
  fullLatex: string;
  onReplace: (from: number, to: number, newText: string) => void;
  onClose: () => void;
}

export default function SelectionToolbar({
  visible,
  position,
  selectedText,
  selectionFrom,
  selectionTo,
  fullLatex,
  onReplace,
  onClose,
}: SelectionToolbarProps) {
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const currentProject = useProjectStore((s) => s.currentProject);

  useEffect(() => {
    if (!visible) {
      setInstruction('');
    }
  }, [visible]);

  // Close toolbar when clicking outside
  useEffect(() => {
    if (!visible) return;
    const handler = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [visible, onClose]);

  if (!visible) return null;

  const handleSubmit = async () => {
    if (!instruction.trim()) {
      message.warning('请输入修改指令');
      return;
    }
    if (!currentProject?.id) {
      message.error('未找到当前项目');
      return;
    }

    setLoading(true);
    let result = '';
    try {
      for await (const event of editSelection({
        projectId: currentProject.id,
        fullLatex,
        selectedText,
        instruction: instruction.trim(),
        selectionStart: selectionFrom,
        selectionEnd: selectionTo,
      })) {
        if (event.type === 'chunk') {
          result += event.data;
        } else if (event.type === 'done') {
          // done event carries cleaned content (extract_latex applied);
          // prefer it over raw streamed chunks (even if empty — deletion is valid)
          result = event.data ?? result;
          break;
        } else if (event.type === 'error') {
          message.error(`AI 修改失败: ${event.data}`);
          setLoading(false);
          return;
        }
      }

      // Empty result is valid — e.g., user asked to delete the selection
      onReplace(selectionFrom, selectionTo, result);
      message.success(result ? 'AI 修改完成' : 'AI 已删除选中内容');
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '请求失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      ref={toolbarRef}
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        zIndex: 1000,
        background: '#fff',
        borderRadius: 8,
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.15)',
        padding: '8px 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        minWidth: 320,
      }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <EditOutlined style={{ color: '#1677ff', fontSize: 16, flexShrink: 0 }} />
      <Input
        placeholder="输入修改指令，如：改成表格、精简这段..."
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        onPressEnter={handleSubmit}
        disabled={loading}
        size="small"
        style={{ flex: 1 }}
      />
      <Button
        type="primary"
        size="small"
        onClick={handleSubmit}
        disabled={loading || !instruction.trim()}
        icon={loading ? <LoadingOutlined /> : undefined}
      >
        {loading ? 'AI 修改中...' : 'AI 修改'}
      </Button>
    </div>
  );
}
