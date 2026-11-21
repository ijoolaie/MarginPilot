import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export function TrendChart({ option }: { option: EChartsOption }) {
  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 340, width: "100%" }} notMerge />;
}

