import type { Metadata } from "next";
import Simulator from "./simulator";

export const metadata: Metadata = {
  title: "舔狗模拟器 · 把旧聊天练成新对话",
  description: "在本地导入、标注和训练你的聊天记录，然后以舔狗或被舔者身份继续对话。",
};

export default function Home() {
  return <Simulator />;
}
