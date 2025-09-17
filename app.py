import streamlit as st
import requests
from xml.etree import ElementTree
import pandas as pd
import re
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import io
from urllib.parse import urlparse
import time

st.set_page_config(
    page_title="Domain Page Counter", 
    page_icon="🔍",
    layout="wide"
)

st.title("🔍 Domain Page Counter")
st.caption("Quickly analyse domain page counts from sitemaps")

def clean_domain(url_or_domain):
    """Clean and standardise domain input"""
    if not url_or_domain:
        return None
    
    url_or_domain = url_or_domain.strip()
    
    # If it looks like a full URL, extract domain
    if url_or_domain.startswith(('http://', 'https://')):
        parsed = urlparse(url_or_domain)
        domain = parsed.netloc
    else:
        domain = url_or_domain
    
    # Remove www and clean
    domain = re.sub(r'^www\.', '', domain.lower())
    domain = domain.rstrip('/')
    
    return domain if domain else None

def get_page_count(domain, timeout_seconds=15):
    """Get page count with comprehensive timeout handling"""
    if not domain:
        return 0, "Invalid domain"
    
    # List of common sitemap locations to try
    sitemap_urls = [
        f"https://{domain}/sitemap.xml",
        f"https://www.{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"https://www.{domain}/sitemap_index.xml"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; PageCounter/1.0)'
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    total_pages = 0
    method = "No sitemap found"
    
    for sitemap_url in sitemap_urls:
        try:
            response = session.get(sitemap_url, timeout=timeout_seconds)
            
            if response.status_code == 200:
                try:
                    root = ElementTree.fromstring(response.content)
                    
                    # Check if it's a sitemap index
                    sitemap_elements = root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap')
                    
                    if sitemap_elements:
                        # It's a sitemap index - get all individual sitemaps
                        individual_sitemaps = []
                        for sitemap in sitemap_elements:
                            loc = sitemap.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
                            if loc is not None:
                                individual_sitemaps.append(loc.text)
                        
                        # Count URLs in all individual sitemaps
                        for individual_sitemap in individual_sitemaps[:10]:  # Limit to 10 sitemaps to avoid timeout
                            try:
                                sub_response = session.get(individual_sitemap, timeout=timeout_seconds)
                                if sub_response.status_code == 200:
                                    sub_root = ElementTree.fromstring(sub_response.content)
                                    urls = sub_root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url')
                                    total_pages += len(urls)
                            except:
                                continue  # Skip failed individual sitemaps
                        
                        method = f"Sitemap index ({len(individual_sitemaps)} sitemaps)"
                        break
                    else:
                        # It's a regular sitemap
                        urls = root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}url')
                        total_pages = len(urls)
                        method = "Single sitemap"
                        break
                        
                except ElementTree.ParseError:
                    continue  # Try next sitemap URL
                    
        except (requests.RequestException, TimeoutError):
            continue  # Try next sitemap URL
    
    # If no pages found, try to at least verify the domain exists
    if total_pages == 0:
        try:
            response = session.get(f"https://{domain}", timeout=5)
            if response.status_code == 200:
                total_pages = 1
                method = "Homepage only (estimate)"
        except:
            method = "Domain inaccessible"
    
    return total_pages, method

def process_domains_batch(domains, progress_callback=None):
    """Process domains with timeout and progress tracking"""
    results = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        future_to_domain = {
            executor.submit(get_page_count, domain, 20): domain 
            for domain in domains
        }
        
        completed = 0
        for future in as_completed(future_to_domain, timeout=300):  # 5 minute overall timeout
            domain = future_to_domain[future]
            try:
                pages, method = future.result(timeout=25)  # Individual task timeout
                results.append({
                    'Domain': domain,
                    'Pages': pages,
                    'Method': method
                })
            except TimeoutError:
                results.append({
                    'Domain': domain,
                    'Pages': 0,
                    'Method': 'Timeout'
                })
            except Exception as e:
                results.append({
                    'Domain': domain,
                    'Pages': 0,
                    'Method': f'Error: {str(e)[:50]}'
                })
            
            completed += 1
            if progress_callback:
                progress_callback(completed, len(domains))
    
    return results

# Main interface
st.markdown("### Enter URLs or Domains")
st.markdown("Paste your list below (one per line). URLs will be converted to domains automatically.")

url_input = st.text_area(
    label="URLs/Domains",
    placeholder="https://example.com\nhttps://another-site.co.uk\nexample.org",
    height=200,
    label_visibility="collapsed"
)

col1, col2 = st.columns([1, 3])

with col1:
    analyze_button = st.button("🔍 Analyse Domains", type="primary")

with col2:
    if url_input:
        lines = [line.strip() for line in url_input.split('\n') if line.strip()]
        domains = [clean_domain(line) for line in lines]
        domains = [d for d in domains if d]  # Remove None values
        unique_domains = list(dict.fromkeys(domains))  # Remove duplicates
        
        if unique_domains:
            st.info(f"Found {len(unique_domains)} unique domains to analyse")

# Process domains when button is clicked
if analyze_button and url_input:
    lines = [line.strip() for line in url_input.split('\n') if line.strip()]
    domains = [clean_domain(line) for line in lines]
    domains = [d for d in domains if d]
    unique_domains = list(dict.fromkeys(domains))
    
    if unique_domains:
        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(completed, total):
            progress = completed / total
            progress_bar.progress(progress)
            status_text.text(f"Analysed {completed}/{total} domains")
        
        start_time = time.time()
        
        # Process domains
        results = process_domains_batch(unique_domains, update_progress)
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Clear progress indicators
        progress_bar.empty()
        status_text.empty()
        
        if results:
            # Convert to DataFrame
            df = pd.DataFrame(results)
            
            # Display results
            st.success(f"Analysis complete! Processed {len(results)} domains in {processing_time:.1f} seconds")
            
            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)
            
            successful = len(df[df['Pages'] > 0])
            total_pages = df['Pages'].sum()
            avg_pages = df[df['Pages'] > 0]['Pages'].mean() if successful > 0 else 0
            
            with col1:
                st.metric("Domains Processed", len(results))
            with col2:
                st.metric("Successful Scans", successful)
            with col3:
                st.metric("Total Pages Found", f"{total_pages:,}")
            with col4:
                st.metric("Average Pages", f"{avg_pages:,.0f}" if avg_pages > 0 else "N/A")
            
            # Show results table
            st.markdown("### Results")
            
            # Sort by pages descending
            df_display = df.sort_values('Pages', ascending=False)
            st.dataframe(df_display, use_container_width=True)
            
            # Create Excel file for download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Main results
                df_export = df[['Domain', 'Pages']].sort_values('Pages', ascending=False)
                df_export.to_excel(writer, sheet_name='Results', index=False)
                
                # Summary sheet
                summary_data = {
                    'Metric': [
                        'Total Domains Processed',
                        'Successful Scans',
                        'Total Pages Found',
                        'Average Pages (successful scans)',
                        'Processing Time (seconds)'
                    ],
                    'Value': [
                        len(results),
                        successful,
                        total_pages,
                        f"{avg_pages:.0f}" if avg_pages > 0 else "N/A",
                        f"{processing_time:.1f}"
                    ]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                
                # Detailed results with method
                df.sort_values('Pages', ascending=False).to_excel(
                    writer, sheet_name='Detailed', index=False
                )
            
            excel_data = output.getvalue()
            
            # Download button
            st.download_button(
                label="📥 Download Results (Excel)",
                data=excel_data,
                file_name=f"domain_page_count_{int(time.time())}.xlsx",
                mime="application/vnd.openxlxml"
            )
            
            # Show any issues
            failed_domains = df[df['Pages'] == 0]
            if not failed_domains.empty:
                with st.expander(f"⚠️ Issues with {len(failed_domains)} domains"):
                    st.dataframe(failed_domains[['Domain', 'Method']], use_container_width=True)
    else:
        st.error("Please enter valid URLs or domains")

# Sidebar info
with st.sidebar:
    st.markdown("### How it works")
    st.markdown("""
    1. **Input**: Paste URLs or domains (one per line)
    2. **Analysis**: Checks common sitemap locations
    3. **Export**: Download results as Excel file
    
    **Timeout Settings:**
    - Individual domain: 20 seconds
    - Overall process: 5 minutes
    - Max concurrent: 10 domains
    """)
    
    st.markdown("### Supported Formats")
    st.code("""
https://example.com
www.example.com
example.com
example.co.uk
    """)
    
    st.markdown("---")
    st.markdown("*Built for quick domain analysis*")
