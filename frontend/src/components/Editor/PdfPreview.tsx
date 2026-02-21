import { Empty } from 'antd';

interface PdfPreviewProps {
  pdfUrl: string | null;
}

export default function PdfPreview({ pdfUrl }: PdfPreviewProps) {
  if (!pdfUrl) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
        }}
      >
        <Empty description="请先编译生成 PDF" />
      </div>
    );
  }

  return (
    <iframe
      src={`${pdfUrl}#view=FitH`}
      style={{
        width: '100%',
        height: '100%',
        border: 'none',
      }}
      title="PDF Preview"
    />
  );
}
