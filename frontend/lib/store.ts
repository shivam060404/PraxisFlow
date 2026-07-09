import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Task, Meeting, User } from "@/lib/api";

interface UIState {
  // Sidebar
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;

  // Task Detail Panel
  selectedTask: Task | null;
  openTaskDetail: (task: Task) => void;
  closeTaskDetail: () => void;

  // Meeting Context View
  selectedMeeting: Meeting | null;
  openMeetingContext: (meeting: Meeting) => void;
  closeMeetingContext: () => void;

  // Filters
  taskFilters: TaskFilters;
  setTaskFilters: (filters: Partial<TaskFilters>) => void;
  clearTaskFilters: () => void;

  // View Mode
  viewMode: "kanban" | "list";
  setViewMode: (mode: "kanban" | "list") => void;

  // Notifications
  notifications: Notification[];
  addNotification: (notification: Omit<Notification, "id">) => void;
  removeNotification: (id: string) => void;
  clearNotifications: () => void;
}

interface TaskFilters {
  status?: string[];
  assignee_id?: string[];
  meeting_id?: string[];
  priority?: string[];
  task_type?: string[];
  search?: string;
  date_from?: string;
  date_to?: string;
}

interface Notification {
  id: string;
  type: "success" | "error" | "warning" | "info";
  title: string;
  message?: string;
  duration?: number;
}

const defaultFilters: TaskFilters = {};

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      // Sidebar
      sidebarOpen: true,
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),

      // Task Detail
      selectedTask: null,
      openTaskDetail: (task) => set({ selectedTask: task }),
      closeTaskDetail: () => set({ selectedTask: null }),

      // Meeting Context
      selectedMeeting: null,
      openMeetingContext: (meeting) => set({ selectedMeeting: meeting }),
      closeMeetingContext: () => set({ selectedMeeting: null }),

      // Filters
      taskFilters: defaultFilters,
      setTaskFilters: (filters) =>
        set((state) => ({ taskFilters: { ...state.taskFilters, ...filters } })),
      clearTaskFilters: () => set({ taskFilters: defaultFilters }),

      // View Mode
      viewMode: "kanban",
      setViewMode: (mode) => set({ viewMode: mode }),

      // Notifications
      notifications: [],
      addNotification: (notification) =>
        set((state) => ({
          notifications: [
            ...state.notifications,
            { ...notification, id: crypto.randomUUID() },
          ],
        })),
      removeNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),
      clearNotifications: () => set({ notifications: [] }),
    }),
    {
      name: "ami-ui-state",
      partialize: (state) => ({
        sidebarOpen: state.sidebarOpen,
        viewMode: state.viewMode,
        taskFilters: state.taskFilters,
      }),
    }
  )
);

// Auth store
interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      setUser: (user) => set({ user }),
      isLoading: true,
      setIsLoading: (loading) => set({ isLoading: loading }),
    }),
    {
      name: "ami-auth",
      partialize: (state) => ({ user: state.user }),
    }
  )
);