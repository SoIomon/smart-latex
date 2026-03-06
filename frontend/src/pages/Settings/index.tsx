import { useEffect, useState } from 'react';
import { Card, Form, Input, Button, message, Space, Typography, Spin, Alert, Tag, Collapse } from 'antd';
import { SaveOutlined, ApiOutlined, MedicineBoxOutlined, CheckCircleOutlined, WarningOutlined, CloseCircleOutlined, DownloadOutlined } from '@ant-design/icons';
import { getLLMConfig, updateLLMConfig, testLLMConnection, runDiagnostics, installFonts } from '../../api/settings';
import type { DiagnosticItem, DiagnosticsResult } from '../../api/settings';

const { Title, Text } = Typography;

export default function Settings() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [currentMaskedKey, setCurrentMaskedKey] = useState('');
  const [diagLoading, setDiagLoading] = useState(false);
  const [diagResult, setDiagResult] = useState<DiagnosticsResult | null>(null);
  const [fontInstalling, setFontInstalling] = useState(false);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        setLoading(true);
        const config = await getLLMConfig();
        form.setFieldsValue({
          base_url: config.base_url,
          model: config.model,
          api_key: '',
        });
        setCurrentMaskedKey(config.api_key_masked);
      } catch {
        message.error('加载配置失败');
      } finally {
        setLoading(false);
      }
    };
    loadConfig();
  }, [form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      setTestResult(null);

      const params: { api_key?: string; base_url: string; model: string } = {
        base_url: values.base_url,
        model: values.model,
      };
      if (values.api_key) params.api_key = values.api_key;

      const config = await updateLLMConfig(params);
      setCurrentMaskedKey(config.api_key_masked);
      form.setFieldValue('api_key', '');
      message.success('配置已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    try {
      const values = await form.validateFields(['base_url', 'model']);
      setTesting(true);
      setTestResult(null);

      const params: Record<string, string> = {};
      const apiKey = form.getFieldValue('api_key');
      if (apiKey) params.api_key = apiKey;
      if (values.base_url) params.base_url = values.base_url;
      if (values.model) params.model = values.model;

      const result = await testLLMConnection(params);
      setTestResult(result);
    } catch {
      setTestResult({ success: false, message: '请求失败' });
    } finally {
      setTesting(false);
    }
  };

  const handleDiagnostics = async () => {
    setDiagLoading(true);
    setDiagResult(null);
    try {
      const result = await runDiagnostics();
      setDiagResult(result);
    } catch {
      message.error('环境检测失败');
    } finally {
      setDiagLoading(false);
    }
  };

  const handleFontInstall = async () => {
    setFontInstalling(true);
    try {
      const result = await installFonts();
      if (result.status === 'ok') {
        message.success(result.message);
        // Re-run diagnostics to refresh font status
        handleDiagnostics();
      } else {
        message.error(result.message);
      }
    } catch {
      message.error('字体安装失败');
    } finally {
      setFontInstalling(false);
    }
  };

  const statusIcon = (status: DiagnosticItem['status']) => {
    if (status === 'ok') return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    if (status === 'warning') return <WarningOutlined style={{ color: '#faad14' }} />;
    return <CloseCircleOutlined style={{ color: '#f5222d' }} />;
  };

  const statusTag = (status: DiagnosticItem['status']) => {
    if (status === 'ok') return <Tag color="success">正常</Tag>;
    if (status === 'warning') return <Tag color="warning">警告</Tag>;
    return <Tag color="error">异常</Tag>;
  };

  return (
    <div style={{ maxWidth: 640, margin: '24px auto', padding: '0 16px' }}>
      <Title level={3}>模型设置</Title>
      <Text type="secondary">配置 LLM 后端的 API 连接参数，修改后立即生效。</Text>

      <Card style={{ marginTop: 16 }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : (
          <Form form={form} layout="vertical">
            <Form.Item
              label="API Key"
              name="api_key"
              help={currentMaskedKey ? `当前: ${currentMaskedKey}（留空则不更新）` : undefined}
            >
              <Input.Password placeholder="输入新的 API Key（留空不更新）" />
            </Form.Item>

            <Form.Item
              label="Base URL"
              name="base_url"
              rules={[{ required: true, message: '请输入 Base URL' }]}
            >
              <Input placeholder="https://ark.cn-beijing.volces.com/api/v3" />
            </Form.Item>

            <Form.Item
              label="Model"
              name="model"
              rules={[{ required: true, message: '请输入模型名称' }]}
            >
              <Input placeholder="doubao-pro-32k 或 endpoint ID" />
            </Form.Item>

            {testResult && (
              <Alert
                type={testResult.success ? 'success' : 'error'}
                message={testResult.message}
                showIcon
                closable
                onClose={() => setTestResult(null)}
                style={{ marginBottom: 16 }}
              />
            )}

            <Form.Item>
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={handleSave}
                >
                  保存
                </Button>
                <Button
                  icon={<ApiOutlined />}
                  loading={testing}
                  onClick={handleTest}
                >
                  测试连接
                </Button>
              </Space>
            </Form.Item>
          </Form>
        )}
      </Card>

      <Title level={3} style={{ marginTop: 32 }}>环境检测</Title>
      <Text type="secondary">检查 LaTeX 编译器、字体等运行环境是否就绪。</Text>

      <Card style={{ marginTop: 16 }}>
        <Space>
          <Button
            icon={<MedicineBoxOutlined />}
            loading={diagLoading}
            onClick={handleDiagnostics}
            type="primary"
            ghost
          >
            运行环境检测
          </Button>
          <Button
            icon={<DownloadOutlined />}
            loading={fontInstalling}
            onClick={handleFontInstall}
          >
            安装内置字体
          </Button>
        </Space>

        {diagResult && (
          <div style={{ marginTop: 16 }}>
            <Text strong>平台: </Text>
            <Text>{diagResult.platform}</Text>

            <div style={{ marginTop: 12 }}>
              {diagResult.items.map((item, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    padding: '8px 0',
                    borderBottom: idx < diagResult.items.length - 1 ? '1px solid #f0f0f0' : undefined,
                  }}
                >
                  <span style={{ marginRight: 8, marginTop: 2 }}>{statusIcon(item.status)}</span>
                  <div style={{ flex: 1 }}>
                    <div>
                      <Text strong>{item.name}</Text>
                      {' '}
                      {statusTag(item.status)}
                    </div>
                    <Text type="secondary" style={{ fontSize: 13 }}>{item.message}</Text>
                    {item.suggestion && (
                      <Collapse
                        ghost
                        size="small"
                        items={[{
                          key: '1',
                          label: <Text type="secondary" style={{ fontSize: 12 }}>查看建议</Text>,
                          children: (
                            <Text
                              style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}
                              copyable
                            >
                              {item.suggestion}
                            </Text>
                          ),
                        }]}
                        style={{ marginTop: 4, marginLeft: -16 }}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>

            {diagResult.items.every(i => i.status === 'ok') && (
              <Alert
                type="success"
                message="所有检测项均正常，环境就绪！"
                showIcon
                style={{ marginTop: 12 }}
              />
            )}
            {diagResult.items.some(i => i.status === 'error') && (
              <Alert
                type="error"
                message="存在异常项，可能影响文档生成和编译功能。请参考各项建议进行修复。"
                showIcon
                style={{ marginTop: 12 }}
              />
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
