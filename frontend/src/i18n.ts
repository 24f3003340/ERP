const dict: Record<string, [string, string]> = {
  home: ["Home", "होम"], billing: ["Billing", "बिलिंग"], invoices: ["Invoices", "इनवॉइस"], products: ["Products & Stock", "प्रोडक्ट और स्टॉक"],
  purchases: ["Purchases", "खरीद"], customers: ["Customers", "ग्राहक"], suppliers: ["Suppliers", "सप्लायर"], accounts: ["Accounts", "खाते"],
  reports: ["Reports", "रिपोर्ट"], settings: ["Settings", "सेटिंग्स"], logout: ["Logout", "लॉगआउट"],
  salesToday: ["Sales today", "आज की बिक्री"], bills: ["Bills", "बिल"], cash: ["Cash", "नकद"], receivables: ["Receivables", "लेना बाकी"],
  payables: ["Payables", "देना बाकी"], lowStock: ["Low stock", "कम स्टॉक"], save: ["Save", "सेव"], cancel: ["Cancel", "रद्द"],
  total: ["Total", "कुल"], search: ["Search / scan barcode", "खोजें / बारकोड स्कैन करें"], newBill: ["New Bill", "नया बिल"],
};
let loc = localStorage.getItem("erp_locale") || "en";
export const setLocale = (l: string) => { loc = l; localStorage.setItem("erp_locale", l); };
export const getLocale = () => loc;
export const t = (k: string) => (dict[k] ? dict[k][loc === "hi" ? 1 : 0] : k);
