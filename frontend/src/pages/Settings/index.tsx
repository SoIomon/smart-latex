import { useEffect, useState } from 'react';
import { Card, Form, Input, Button, message, Space, Typography, Spin, Alert } from 'antd';
import { SaveOutlined, ApiOutlined } from '@ant-design/icons';
import { getLLMConfig, updateLLMConfig, testLLMConnection } from '../../api/settings';

const { Title, Text } = Typography;

export default function Settings() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [currentMaskedKey, setCurrentMaskedKey] = useState('');

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
    </div>
  );
}
