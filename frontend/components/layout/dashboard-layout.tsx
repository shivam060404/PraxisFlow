"use client";

import { ReactNode, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sidebar, SidebarContent, SidebarGroup, SidebarMenu, SidebarMenuItem, SidebarMenuButton } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import {
  LayoutDashboard,
  Calendar,
  ListChecks,
  BarChart3,
  Settings,
  Users,
  ChevronLeft,
  ChevronRight,
  Upload,
  Mic,
} from "lucide-react";
import { useAuthStore } from "@/lib/store";

const navigation = [
  { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { name: "Execution Board", href: "/dashboard/board", icon: ListChecks },
  { name: "Meetings", href: "/dashboard/meetings", icon: Calendar },
  { name: "Team Metrics", href: "/dashboard/metrics", icon: BarChart3 },
  { name: "Team", href: "/dashboard/team", icon: Users },
  { name: "Settings", href: "/dashboard/settings", icon: Settings },
];

export function DashboardLayout({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const { user } = useAuthStore();

  return (
    <Sidebar>
      <SidebarContent className={cn("transition-all duration-300", collapsed && "w-16")}>
        <SidebarGroup>
          <SidebarMenu>
            <SidebarMenuItem className="px-4 py-2">
              <Link href="/dashboard" className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
                  <Mic className="h-5 w-5 text-primary-foreground" />
                </div>
                {!collapsed && (
                  <span className="font-semibold text-lg">AMI</span>
                )}
              </Link>
            </SidebarMenuItem>
            <Separator className="my-2" />
            {navigation.map((item) => {
              const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <SidebarMenuItem key={item.name} className="px-2">
                  <SidebarMenuButton
                    asChild
                    className={cn(
                      "gap-3 transition-colors",
                      isActive && "bg-accent text-accent-foreground"
                    )}
                  >
                    <Link href={item.href}>
                      <item.icon className="h-5 w-5 flex-shrink-0" />
                      {!collapsed && <span>{item.name}</span>}
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
        
        <SidebarGroup className="mt-auto">
          <SidebarMenu>
            <SidebarMenuItem className="px-4 py-2">
              {!collapsed && user && (
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary">
                    <span className="text-xs font-medium text-primary-foreground">
                      {user.full_name?.charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{user.full_name}</p>
                    <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                  </div>
                </div>
              )}
              {collapsed && user && (
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary mx-auto">
                  <span className="text-xs font-medium text-primary-foreground">
                    {user.full_name?.charAt(0).toUpperCase()}
                  </span>
                </div>
              )}
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroup>
        
        <Button
          variant="ghost"
          size="icon"
          className="absolute bottom-4 right-2 mx-auto w-8 h-8"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </SidebarContent>
      
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </Sidebar>
  );
}