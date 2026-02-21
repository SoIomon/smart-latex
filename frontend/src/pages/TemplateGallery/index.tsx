import { useEffect, useState } from 'react';
import { Card, Row, Col, Typography, Spin, Empty, Button, message, Popconfirm, Modal } from 'antd';
import { FileTextOutlined, DeleteOutlined, EyeOutlined, CrownOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getTemplates, deleteTemplate, getTemplateContent } from '../../api/templates';
import { useProjectStore } from '../../stores/projectStore';
import TemplateGenerateModal from '../../components/DocumentPanel/TemplateGenerateModal';
import type { Template } from '../../types';

const { Title, Paragraph } = Typography;

export default function TemplateGallery() {
  const navigate = useNavigate();
  const { createProject } = useProjectStore();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState('');
  const [previewName, setPreviewName] = useState('');
  const [previewOpen, setPreviewOpen] = useState(false);
  const [generateModalOpen, setGenerateModalOpen] = useState(false);

  const fetchTemplates = () => {
    setLoading(true);
    getTemplates()
      .then(setTemplates)
      .catch(() => message.error('加载模板失败'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  const handleUseTemplate = async (template: Template) => {
    setCreating(template.id);
    try {
      const project = await createProject({
        name: `${template.name} - 新项目`,
        description: `基于模板 "${template.name}" 创建`,
        template_id: template.id,
      });
      message.success('项目创建成功');
      navigate(`/workspace/${project.id}`);
    } catch {
      message.error('创建项目失败');
    } finally {
      setCreating(null);
    }
  };

  const handleDelete = async (template: Template) => {
    try {
      await deleteTemplate(template.id);
      message.success('模板已删除');
      fetchTemplates();
    } catch {
      message.error('删除失败');
    }
  };

  const handlePreview = async (template: Template) => {
    try {
      const content = await getTemplateContent(template.id);
      setPreviewContent(content);
      setPreviewName(template.name);
      setPreviewOpen(true);
    } catch {
      message.error('获取模板内容失败');
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          模板库
        </Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setGenerateModalOpen(true)}
        >
          生成模板
        </Button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
        </div>
      ) : templates.length === 0 ? (
        <Empty description="暂无可用模板">
          <Button type="primary" onClick={() => setGenerateModalOpen(true)}>
            生成第一个模板
          </Button>
        </Empty>
      ) : (
        <Row gutter={[16, 16]}>
          {templates.map((template) => (
            <Col key={template.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                cover={
                  <div
                    style={{
                      height: 160,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      background: template.is_builtin ? '#f0f5ff' : '#f6ffed',
                    }}
                  >
                    <FileTextOutlined
                      style={{ fontSize: 48, color: template.is_builtin ? '#1677ff' : '#52c41a' }}
                    />
                  </div>
                }
                actions={[
                  <Button
                    key="use"
                    type="link"
                    size="small"
                    loading={creating === template.id}
                    onClick={() => handleUseTemplate(template)}
                  >
                    使用
                  </Button>,
                  <Button
                    key="preview"
                    type="link"
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => handlePreview(template)}
                  >
                    预览
                  </Button>,
                  ...(template.is_builtin
                    ? []
                    : [
                        <Popconfirm
                          key="delete"
                          title="确定删除此模板？"
                          onConfirm={() => handleDelete(template)}
                          okText="删除"
                          cancelText="取消"
                        >
                          <Button
                            type="link"
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                          >
                            删除
                          </Button>
                        </Popconfirm>,
                      ]),
                ]}
              >
                <Card.Meta
                  title={
                    <span>
                      {template.name}
                      {template.is_builtin && (
                        <CrownOutlined style={{ marginLeft: 6, color: '#faad14', fontSize: 12 }} />
                      )}
                    </span>
                  }
                  description={
                    <Paragraph
                      ellipsis={{ rows: 2 }}
                      style={{ marginBottom: 0, fontSize: 12 }}
                    >
                      {template.description}
                    </Paragraph>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title={`模板预览 - ${previewName}`}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={800}
      >
        <pre
          style={{
            maxHeight: 500,
            overflow: 'auto',
            background: '#f5f5f5',
            borderRadius: 6,
            padding: 16,
            fontSize: 12,
            fontFamily: '"Fira Code", "Consolas", monospace',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {previewContent}
        </pre>
      </Modal>

      <TemplateGenerateModal
        open={generateModalOpen}
        onClose={() => setGenerateModalOpen(false)}
        onSuccess={fetchTemplates}
      />
    </div>
  );
}
