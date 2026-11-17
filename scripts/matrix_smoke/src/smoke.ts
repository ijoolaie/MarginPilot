/* Matrix smoke: exercises every pinned family once (no business logic). */
import { init } from "echarts";
import { z } from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { QueryClient } from "@tanstack/react-query";
import { Routes } from "react-router";
import "vazirmatn/Vazirmatn-font-face.css";
import "./index.css";

const schema = z.object({ price: z.number().min(0) });
type FormValues = z.infer<typeof schema>;

export function smokeAll(): void {
  const queryClient = new QueryClient(); // @tanstack/react-query
  const form = useForm<FormValues>({ resolver: zodResolver(schema) }); // RHF + zod + resolvers
  init(document.createElement("div")); // echarts
  void Routes; // react-router
  void queryClient;
  void form;
}
