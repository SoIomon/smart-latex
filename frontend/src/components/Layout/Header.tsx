import { Layout, Menu } from 'antd';
import { FileTextOutlined, AppstoreOutlined, SettingOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';

const { Header: AntHeader } = Layout;

export default function Header() {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    { key: '/', label: '我的项目', icon: <FileTextOutlined /> },
    { key: '/templates', label: '模板库', icon: <AppstoreOutlined /> },
    { key: '/settings', label: '设置', icon: <SettingOutlined /> },
  ];

  const selectedKey = location.pathname.startsWith('/templates')
    ? '/templates'
    : location.pathname.startsWith('/settings')
      ? '/settings'
      : '/';

  return (
    <AntHeader
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        background: '#001529',
      }}
    >
      <div
        style={{
          color: '#fff',
          fontSize: 20,
          fontWeight: 700,
          marginRight: 40,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}
        onClick={() => navigate('/')}
      >
        Smart LaTeX
      </div>
      <Menu
        theme="dark"
        mode="horizontal"
        selectedKeys={[selectedKey]}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        style={{ flex: 1, minWidth: 0 }}
      />
    </AntHeader>
  );
}
