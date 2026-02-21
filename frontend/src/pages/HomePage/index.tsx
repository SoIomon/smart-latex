import { useEffect, useState } from 'react';
import {
  Card,
  Row,
  Col,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Typography,
  Spin,
  Empty,
  Popconfirm,
  message,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useProjectStore } from '../../stores/projectStore';
import { getTemplates } from '../../api/templates';
import type { Template } from '../../types';

const { Title, Text, Paragraph } = Typography;

export default function HomePage() {
  const navigate = useNavigate();
  const { projects, loading, fetchProjects, createProject, deleteProject } =
    useProjectStore();
  const [modalOpen, setModalOpen] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    fetchProjects();
    getTemplates()
      .then(setTemplates)
      .catch(() => {});
  }, [fetchProjects]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setCreating(true);
      const project = await createProject(values);
      message.success('项目创建成功');
      setModalOpen(false);
      form.resetFields();
      navigate(`/workspace/${project.id}`);
    } catch {
      // validation failed or API error
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteProject(id);
      message.success('项目已删除');
    } catch {
      message.error('删除失败');
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
        }}
      >
        <Title level={3} style={{ margin: 0 }}>
          我的项目
        </Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setModalOpen(true)}
        >
          新建项目
        </Button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
        </div>
      ) : projects.length === 0 ? (
        <Empty description="暂无项目，点击上方按钮创建">
          <Button type="primary" onClick={() => setModalOpen(true)}>
            创建第一个项目
          </Button>
        </Empty>
      ) : (
        <Row gutter={[16, 16]}>
          {projects.map((project) => (
            <Col key={project.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                onClick={() => navigate(`/workspace/${project.id}`)}
                actions={[
                  <EditOutlined
                    key="edit"
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(`/workspace/${project.id}`);
                    }}
                  />,
                  <Popconfirm
                    key="delete"
                    title="确定删除此项目?"
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      handleDelete(project.id);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="删除"
                    cancelText="取消"
                  >
                    <DeleteOutlined
                      onClick={(e) => e.stopPropagation()}
                      style={{ color: '#ff4d4f' }}
                    />
                  </Popconfirm>,
                ]}
              >
                <Card.Meta
                  avatar={
                    <FolderOpenOutlined
                      style={{ fontSize: 28, color: '#1677ff' }}
                    />
                  }
                  title={project.name}
                  description={
                    <>
                      <Paragraph
                        ellipsis={{ rows: 2 }}
                        style={{ marginBottom: 4, fontSize: 12, color: '#999' }}
                      >
                        {project.description || '暂无描述'}
                      </Paragraph>
                      {project.template_name && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          模板: {project.template_name}
                        </Text>
                      )}
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {formatDate(project.updated_at)}
                      </Text>
                    </>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title="新建项目"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
        }}
        confirmLoading={creating}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="输入项目名称" />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea placeholder="简要描述 (可选)" rows={2} />
          </Form.Item>
          <Form.Item name="template_id" label="选择模板">
            <Select
              placeholder="选择模板 (可选)"
              allowClear
              options={templates.map((t) => ({
                label: t.name,
                value: t.id,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
