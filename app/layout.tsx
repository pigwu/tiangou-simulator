import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "舔狗模拟器",
  description: "隐私优先的本地聊天角色训练与模拟器。",
  openGraph: {
    title: "舔狗模拟器",
    description: "把过去的消息，变成一场新的对话",
    images: [{ url: "/og.png", width: 1672, height: 941, alt: "舔狗模拟器项目封面" }],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
